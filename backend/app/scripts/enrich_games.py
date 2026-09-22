"""Phase 2 (+ v3 richer analysis): LLM enrichment batch job. Run manually for now:

    python -m app.scripts.enrich_games [--limit N] [--concurrency N]
    python -m app.scripts.enrich_games --titles-file PATH [--limit N]

Only processes games with no enrichment yet, or where enrichment_version is
stale - re-running is cheap and safe. Use --limit to spot-check a small batch
for accuracy before trusting this at scale (see mvp-plan.md phase 2).

--titles-file restricts the run to exactly the games named in a text file
(one title per line, blank lines skipped, order preserved - no sorting or
deduping). Titles already in `games` are matched against the existing
catalog first (free, no API call); anything not found is pulled in via
IGDB search + HLTB match (the existing igdb_client/hltb_client code, not a
new pipeline) before being enriched. Ambiguous or failed title resolutions
are logged and skipped, never guessed - same matching rules as
scripts/match_backloggd_top100.py (shared via services/title_matching.py).
With --titles-file, --limit caps how many *resolved* games get enriched,
preserving file order (so --titles-file X --limit 10 means "the first 10
titles in X that resolve to a game", not the first 10 lines verbatim).

Runs up to `--concurrency` Claude calls in flight at once (default 6) - a
naive one-at-a-time loop means any API latency multiplies directly into wall
-clock time with nothing else happening in parallel, which is exactly what
made the first version of this script take over an hour for ~400 games.
Concurrency is bounded by a semaphore so this doesn't hammer the API; only
the enrich_game() calls themselves run concurrently, DB writes are still
applied one at a time as each result comes back (AsyncSession isn't safe for
concurrent use), so no game is ever half-written.
"""

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select

from app.db import async_session_factory
from app.models import Game
from app.schemas import HardFilters
from app.services.hltb_client import match_game as hltb_match_game
from app.services.igdb_client import IGDBClient
from app.services.llm_enrichment import ENRICHMENT_VERSION, enrich_game
from app.services.scoring import apply_hard_filters
from app.services.title_matching import classify_match
from app.scripts.sync_igdb import upsert_games

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 6

# Claude Sonnet 5 published API pricing (claude.com/pricing, checked 2026-09-22).
# Cache rates included for completeness even though this prompt doesn't use
# prompt caching (no cache_control set) - cache token counts should be 0.
PRICE_PER_MTOK_INPUT = 2.00
PRICE_PER_MTOK_OUTPUT = 10.00
PRICE_PER_MTOK_CACHE_WRITE = 2.50
PRICE_PER_MTOK_CACHE_READ = 0.20


def _call_cost(usage: dict) -> float:
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    return (
        input_tokens / 1_000_000 * PRICE_PER_MTOK_INPUT
        + output_tokens / 1_000_000 * PRICE_PER_MTOK_OUTPUT
        + cache_write / 1_000_000 * PRICE_PER_MTOK_CACHE_WRITE
        + cache_read / 1_000_000 * PRICE_PER_MTOK_CACHE_READ
    )


def print_report(timings: list["EnrichmentTiming"]) -> None:
    if not timings:
        print("No successful enrichments to report on.")
        return

    total_wall_seconds = sum(t.seconds for t in timings)
    total_input = sum(t.usage.get("input_tokens", 0) or 0 for t in timings)
    total_output = sum(t.usage.get("output_tokens", 0) or 0 for t in timings)
    total_cache_write = sum(t.usage.get("cache_creation_input_tokens", 0) or 0 for t in timings)
    total_cache_read = sum(t.usage.get("cache_read_input_tokens", 0) or 0 for t in timings)
    total_cost = sum(_call_cost(t.usage) for t in timings)
    n = len(timings)

    retried_count = sum(1 for t in timings if t.retried)

    print("\n=== Enrichment report ===")
    print(f"{'Title':45} {'sec':>6} {'in_tok':>8} {'out_tok':>8} {'cost':>10}  retried")
    for t in timings:
        print(f"{t.title[:45]:45} {t.seconds:6.2f} {t.usage.get('input_tokens', 0):8} "
              f"{t.usage.get('output_tokens', 0):8} ${_call_cost(t.usage):9.5f}  {'yes' if t.retried else ''}")
    print("-" * 88)
    print(f"Games enriched:          {n}")
    print(f"Retries needed:          {retried_count}/{n} (one automatic retry on an empty/malformed response)")
    print(f"Total wall time (calls): {total_wall_seconds:.2f}s (sum of per-call time, calls run concurrently)")
    print(f"Total input tokens:      {total_input}")
    print(f"Total output tokens:     {total_output}")
    if total_cache_write or total_cache_read:
        print(f"Total cache write tokens: {total_cache_write}")
        print(f"Total cache read tokens:  {total_cache_read}")
    print(f"Total cost:              ${total_cost:.5f}")
    print(f"Average cost/game:       ${total_cost / n:.5f}")
    print(f"Average time/game:       {total_wall_seconds / n:.2f}s")


def read_titles_file(path: Path) -> list[str]:
    """One title per line, blank lines skipped, original order preserved -
    no sorting, no deduping.
    """
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


@dataclass
class TitleResolutionFailure:
    title: str
    reason: str
    confidence: float | None = None


@dataclass
class TitleResolutionReport:
    already_in_db: list[str] = field(default_factory=list)
    added_from_igdb: list[str] = field(default_factory=list)
    failures: list[TitleResolutionFailure] = field(default_factory=list)


async def resolve_titles(session, titles: list[str]) -> tuple[list[Game], TitleResolutionReport]:
    """Resolve a list of titles (in order) to Game rows. Games missing from
    `games` are pulled in via IGDB search + HLTB match (existing client
    code, no new pipeline). Ambiguous or failed resolutions are skipped and
    reported, never guessed - see this module's docstring.
    """
    resolved: list[Game] = []
    report = TitleResolutionReport()

    existing_result = await session.execute(select(Game))
    known_games = list(existing_result.scalars().all())

    igdb_client = IGDBClient()

    for title in titles:
        game, status, confidence = classify_match(title, known_games)

        if status == "matched":
            resolved.append(game)
            report.already_in_db.append(title)
            continue

        if status == "ambiguous":
            report.failures.append(
                TitleResolutionFailure(title, "ambiguous match against existing games", confidence)
            )
            logger.warning("Skipping %r - ambiguous match against existing games (score %s)", title, confidence)
            continue

        # status == "unmatched" against what's already in the DB - search IGDB.
        try:
            search_results = await igdb_client.search_games(title)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal to the whole run
            report.failures.append(TitleResolutionFailure(title, f"IGDB search failed: {exc!r}"))
            logger.warning("Skipping %r - IGDB search failed: %r", title, exc)
            continue

        if not search_results:
            report.failures.append(TitleResolutionFailure(title, "no IGDB search results"))
            logger.warning("Skipping %r - no IGDB search results", title)
            continue

        # Score IGDB's search results with the same matcher used everywhere
        # else, rather than trusting IGDB's top hit blindly.
        search_candidates = [Game(id=r["id"], name=r["name"]) for r in search_results]
        igdb_game, igdb_status, igdb_confidence = classify_match(title, search_candidates)

        if igdb_status != "matched":
            report.failures.append(
                TitleResolutionFailure(title, f"IGDB search result {igdb_status}", igdb_confidence)
            )
            logger.warning(
                "Skipping %r - IGDB search result %s (top candidates: %s)",
                title,
                igdb_status,
                [r["name"] for r in search_results[:3]],
            )
            continue

        matched_raw = next(r for r in search_results if r["id"] == igdb_game.id)
        await upsert_games(session, [matched_raw])
        db_game = await session.get(Game, igdb_game.id)

        if db_game.hltb_main is None:
            hltb_match = await hltb_match_game(db_game.name)
            if hltb_match is not None:
                db_game.hltb_main = hltb_match.main
                db_game.hltb_main_extra = hltb_match.main_extra
                db_game.hltb_completionist = hltb_match.completionist
                await session.commit()

        resolved.append(db_game)
        known_games.append(db_game)
        report.added_from_igdb.append(title)
        logger.info("Added %r from IGDB (id=%d)", db_game.name, db_game.id)

    return resolved, report


@dataclass
class EnrichmentTiming:
    title: str
    seconds: float
    usage: dict
    retried: bool = False


async def _enrich_bounded(game: Game, semaphore: asyncio.Semaphore):
    """Wraps enrich_game so a failure surfaces as a value, not an exception -
    lets asyncio.as_completed drive the batch without one bad game killing it,
    same resilience as the original try/except-per-game loop had. Also times
    each call for the per-game timing/cost report.
    """
    async with semaphore:
        start = time.monotonic()
        try:
            result = await enrich_game(game)
        except Exception as exc:  # noqa: BLE001 - logged with full context below
            return game, None, exc, time.monotonic() - start
        return game, result, None, time.monotonic() - start


async def run(
    limit: int | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    titles_file: Path | None = None,
) -> tuple[int, int, list[EnrichmentTiming]]:
    """Returns (done, failed, per_game_timings) for the caller to build a report from."""
    async with async_session_factory() as session:
        resolution_report: TitleResolutionReport | None = None

        if titles_file is not None:
            titles = read_titles_file(titles_file)
            logger.info("Resolving %d titles from %s", len(titles), titles_file)
            games, resolution_report = await resolve_titles(session, titles)
            logger.info(
                "Resolved %d/%d titles (%d already in DB, %d added from IGDB, %d failed)",
                len(games),
                len(titles),
                len(resolution_report.already_in_db),
                len(resolution_report.added_from_igdb),
                len(resolution_report.failures),
            )
            if limit is not None:
                games = games[:limit]
        else:
            # apply_hard_filters(HardFilters()) with all-default filters still
            # applies the always-on mobile/DLC exclusion baked into that function
            # - reused here so enrichment never spends a Claude call on a game
            # that can't be recommended anyway, and so the two exclusion rules
            # can't drift apart into two different definitions of "excluded".
            query = apply_hard_filters(HardFilters()).where(
                or_(Game.enrichment_version.is_(None), Game.enrichment_version < ENRICHMENT_VERSION)
            )
            if limit is not None:
                query = query.limit(limit)
            result = await session.execute(query)
            games = list(result.scalars().all())

        logger.info("Enriching %d games (concurrency=%d)", len(games), concurrency)

        semaphore = asyncio.Semaphore(concurrency)
        tasks = [asyncio.create_task(_enrich_bounded(game, semaphore)) for game in games]

        done = 0
        failed = 0
        timings: list[EnrichmentTiming] = []

        for coro in asyncio.as_completed(tasks):
            game, enrichment, exc, elapsed = await coro

            if exc is not None:
                logger.error("Enrichment failed for game %d (%s): %r", game.id, game.name, exc)
                failed += 1
                continue

            game.story_gameplay_ratio = enrichment.story_gameplay_ratio
            game.custom_categories = enrichment.custom_categories
            game.pacing_score = enrichment.pacing_score
            game.mechanical_execution_focus = enrichment.mechanical_execution_focus
            game.core_loop = enrichment.core_loop
            game.tone_atmosphere = enrichment.tone_atmosphere
            game.narrative_style = enrichment.narrative_style
            game.player_fit = enrichment.player_fit
            game.player_fit_mismatch = enrichment.player_fit_mismatch
            game.standout_strengths = enrichment.standout_strengths
            game.common_complaints = enrichment.common_complaints
            game.comparable_games = enrichment.comparable_games
            game.enriched_at = datetime.now(UTC)
            game.enrichment_version = ENRICHMENT_VERSION
            await session.commit()
            done += 1
            timings.append(EnrichmentTiming(game.name, elapsed, enrichment.usage, enrichment.retried))

            if done % 25 == 0:
                logger.info("Progress: %d/%d enriched (%d failed)", done, len(games), failed)

        logger.info("Done. %d enriched, %d failed.", done, failed)
        return done, failed, timings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only enrich the first N pending games")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max Claude calls in flight at once (default {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--titles-file",
        type=Path,
        default=None,
        help="Restrict the run to titles in this file (one per line, order preserved)",
    )
    args = parser.parse_args()
    _, _, timings = asyncio.run(run(args.limit, args.concurrency, args.titles_file))
    print_report(timings)


if __name__ == "__main__":
    main()
