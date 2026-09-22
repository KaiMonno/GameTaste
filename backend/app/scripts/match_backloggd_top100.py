"""Phase 3.6: Backloggd Top 100 benchmark/reference dataset. Matches
Backloggd's Top 100 games list to this project's IGDB-backed `games` table,
for evaluating recommendation quality against a small, recognizable set of
highly-regarded games - see game-recommender-mvp-plan.md Phase 3.6.

This is a benchmark ONLY: never used as the primary catalog, never a
recommendation-scoring input (see services/scoring.py's module docstring).
The point is checking both that the engine CAN surface these games when
they're a genuine match, and that it can ALSO surface strong games outside
this list - not teaching the engine "highly rated = Top 100".

--------------------------------------------------------------------------
KNOWN LIMITATION - this script does not scrape Backloggd itself.

backloggd.com/games/top-100/ is protected by Bunny Shield, a JavaScript
proof-of-work bot challenge. Confirmed blocking:
  - plain HTTP requests (curl, httpx-style fetches): 403 Forbidden
  - this project's other web-fetch tooling: also 403
  - the Wayback Machine: no archived snapshot exists for this URL

Reliably getting past a client-side JS challenge needs a real headless
browser (e.g. Playwright), which is a meaningfully heavier dependency than
anything else in this project (howlongtobeatpy/rapidfuzz for HLTB matching
is the closest precedent, and even that doesn't need a browser). Adding one
just for this benchmark was judged out of scope for this task - see the
task's own "do not expand scope" list.

Until the list is obtained some other way (e.g. a real browser session,
manually copying the current list from backloggd.com), this script expects
the 100 titles as a JSON file:

    [{"rank": 1, "title": "Elden Ring"}, {"rank": 2, "title": "..."}, ...]

at --input (default: app/scripts/data/backloggd_top_100.json - see that
file for the exact expected shape; it ships as an empty list, deliberately
not pre-filled with a guessed/hallucinated list, since that would
misrepresent this as real fetched data). Everything downstream of having
that file - fuzzy-matching each title to a `games` row, flagging ambiguous
matches instead of guessing, storing the result - is fully implemented and
tested (see tests/test_backloggd_matching.py) and needs no changes once the
titles are available.
--------------------------------------------------------------------------

Run manually:

    python -m app.scripts.match_backloggd_top100 [--input PATH]

Expect a meaningful number of "unmatched" entries against today's ~415-game
catalog - Backloggd's Top 100 draws from the full ~190k-game universe this
project intends to eventually sync (see mvp-plan.md section on catalog
scale), not from IGDB's top-500-by-rating-count subset that's synced today.
An unmatched entry here is not a bug in the matcher; it means that game
simply isn't in the catalog yet.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from rapidfuzz import fuzz

from app.db import async_session_factory
from app.models import BackloggdTop100, Game
from app.schemas import HardFilters
from app.services.scoring import apply_hard_filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_INPUT_PATH = Path(__file__).parent / "data" / "backloggd_top_100.json"

# A title is only accepted as a confident match if its best candidate scores
# at least this well...
MIN_MATCH_SCORE = 80
# ...AND beats the next-best candidate by at least this much. Below this
# margin the two candidates are too close to tell apart automatically (e.g.
# a base game vs. its own remaster both scoring ~90) - flagged "ambiguous"
# rather than silently picking one, per the task's explicit requirement.
MIN_AMBIGUITY_MARGIN = 5


def find_best_matches(title: str, candidates: list[Game]) -> list[tuple[Game, float]]:
    """All candidates scored against `title` via rapidfuzz token_sort_ratio
    (same approach as services/hltb_client.py's title matching), best first.
    """
    scored = [(game, fuzz.token_sort_ratio(title, game.name)) for game in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def classify_match(title: str, candidates: list[Game]) -> tuple[Game | None, str, float | None]:
    """Returns (matched_game_or_None, status, confidence). status is one of
    "matched", "ambiguous", "unmatched" - see MIN_MATCH_SCORE/MIN_AMBIGUITY_MARGIN.
    """
    scored = find_best_matches(title, candidates)
    if not scored:
        return None, "unmatched", None

    best_game, best_score = scored[0]
    if best_score < MIN_MATCH_SCORE:
        return None, "unmatched", best_score

    if len(scored) > 1:
        _, second_score = scored[1]
        if best_score - second_score < MIN_AMBIGUITY_MARGIN:
            return None, "ambiguous", best_score

    return best_game, "matched", best_score


async def run(input_path: Path) -> None:
    if not input_path.exists():
        logger.error(
            "No input file at %s - this script does not scrape Backloggd itself, "
            "see the module docstring for why and how to supply the list.",
            input_path,
        )
        return

    entries = json.loads(input_path.read_text())
    if not entries:
        logger.warning(
            "%s exists but is empty - nothing to match. Populate it with the current "
            "Backloggd Top 100 (see this script's module docstring).",
            input_path,
        )
        return

    logger.info("Matching %d Backloggd Top 100 entries", len(entries))

    async with async_session_factory() as session:
        # Only main games (not DLC/expansions, not mobile) are eligible for
        # Backloggd's Top 100 per the task spec, and matching against a DLC
        # entry by name collision would be wrong by definition - reusing
        # apply_hard_filters(HardFilters()) here applies exactly the
        # always-on mobile/DLC exclusion (no other filters set), same as
        # scripts/enrich_games.py already does for the same reason.
        result = await session.execute(apply_hard_filters(HardFilters()))
        candidates = list(result.scalars().all())

        matched = ambiguous = unmatched = 0
        for entry in entries:
            game, status, confidence = classify_match(entry["title"], candidates)

            if status == "matched":
                matched += 1
            elif status == "ambiguous":
                ambiguous += 1
                logger.warning(
                    "Ambiguous match for rank %d %r (top score %.1f, too close to the runner-up) - "
                    "flagged, not guessing",
                    entry["rank"],
                    entry["title"],
                    confidence or 0,
                )
            else:
                unmatched += 1
                logger.warning("No confident match for rank %d %r", entry["rank"], entry["title"])

            row = BackloggdTop100(
                rank=entry["rank"],
                backloggd_title=entry["title"],
                game_id=game.id if game else None,
                match_status=status,
                match_confidence=confidence,
            )
            await session.merge(row)

        await session.commit()
        logger.info("Done. %d matched, %d ambiguous, %d unmatched.", matched, ambiguous, unmatched)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    args = parser.parse_args()
    asyncio.run(run(args.input))


if __name__ == "__main__":
    main()
