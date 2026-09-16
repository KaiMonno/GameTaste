"""Phase 2: LLM enrichment batch job. Run manually for now:

    python -m app.scripts.enrich_games [--limit N] [--concurrency N]

Only processes games with no enrichment yet, or where enrichment_version is
stale - re-running is cheap and safe. Use --limit to spot-check a small batch
for accuracy before trusting this at scale (see mvp-plan.md phase 2).

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
from datetime import UTC, datetime

from sqlalchemy import or_

from app.db import async_session_factory
from app.models import Game
from app.schemas import HardFilters
from app.services.llm_enrichment import ENRICHMENT_VERSION, enrich_game
from app.services.scoring import apply_hard_filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 6


async def _enrich_bounded(game: Game, semaphore: asyncio.Semaphore):
    """Wraps enrich_game so a failure surfaces as a value, not an exception -
    lets asyncio.as_completed drive the batch without one bad game killing it,
    same resilience as the original try/except-per-game loop had.
    """
    async with semaphore:
        try:
            return game, await enrich_game(game), None
        except Exception as exc:  # noqa: BLE001 - logged with full context below
            return game, None, exc


async def run(limit: int | None = None, concurrency: int = DEFAULT_CONCURRENCY) -> None:
    async with async_session_factory() as session:
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
        for coro in asyncio.as_completed(tasks):
            game, enrichment, exc = await coro

            if exc is not None:
                logger.error("Enrichment failed for game %d (%s): %r", game.id, game.name, exc)
                failed += 1
                continue

            game.story_gameplay_ratio = enrichment.story_gameplay_ratio
            game.content_warnings = enrichment.content_warnings
            game.enriched_at = datetime.now(UTC)
            game.enrichment_version = ENRICHMENT_VERSION
            await session.commit()
            done += 1

            if done % 25 == 0:
                logger.info("Progress: %d/%d enriched (%d failed)", done, len(games), failed)

        logger.info("Done. %d enriched, %d failed.", done, failed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only enrich the first N pending games")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max Claude calls in flight at once (default {DEFAULT_CONCURRENCY})",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
