"""Keep the curated recommendation set (see models.CuratedListGame) in sync
with the repo-root `Game List` file. Run after every edit to that file:

    python -m app.scripts.sync_curated_list [--file PATH]

`Game List` is the single source of truth - this script diffs the current
curated_list_games membership against it rather than taking separate add/
remove commands, so editing the list is always just "edit the file, re-run
this script":
  - a title newly in the file gets added (via the same IGDB-search + HLTB-
    match resolution scripts/enrich_games.py's --titles-file mode already
    uses - resolve_titles() is imported from there, not reimplemented here)
  - a title no longer in the file gets removed from the curated set - the
    underlying `games` row and its enrichment are left alone (so re-adding
    it later doesn't re-pay for IGDB search / HLTB match / LLM enrichment)
  - ambiguous or failed resolutions are logged and skipped, never guessed -
    same rule as everywhere else this matching code is used

This script only manages curated_list_games membership - it does not call
the LLM. Run scripts/enrich_games.py afterward (no --titles-file; its
default pending-games query is scoped to the curated set, see
services/scoring.py restrict_to_curated_list) to enrich anything newly added.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from app.db import async_session_factory
from app.models import CuratedListGame
from app.scripts.enrich_games import read_titles_file, resolve_titles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# backend/app/scripts/sync_curated_list.py -> repo root is 3 parents up.
DEFAULT_LIST_PATH = Path(__file__).resolve().parents[3] / "Game List"


async def run(list_path: Path) -> None:
    async with async_session_factory() as session:
        titles = read_titles_file(list_path)
        logger.info("Syncing curated list against %d titles from %s", len(titles), list_path)

        resolved_games, report = await resolve_titles(session, titles)
        logger.info(
            "Resolved %d/%d titles (%d already in DB, %d added from IGDB, %d failed)",
            len(resolved_games),
            len(titles),
            len(report.already_in_db),
            len(report.added_from_igdb),
            len(report.failures),
        )

        resolved_ids = {g.id for g in resolved_games}

        existing_result = await session.execute(select(CuratedListGame))
        existing_members = {row.game_id: row for row in existing_result.scalars().all()}

        to_add = resolved_ids - existing_members.keys()
        to_remove = existing_members.keys() - resolved_ids

        for game_id in to_add:
            session.add(CuratedListGame(game_id=game_id))
        for game_id in to_remove:
            await session.delete(existing_members[game_id])

        await session.commit()

        logger.info(
            "Curated list membership: +%d added, -%d removed, %d unchanged (%d total)",
            len(to_add),
            len(to_remove),
            len(resolved_ids) - len(to_add),
            len(resolved_ids),
        )

        if report.failures:
            logger.warning("%d titles did not resolve and are not in the curated set:", len(report.failures))
            for failure in report.failures:
                logger.warning("  %r - %s", failure.title, failure.reason)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_LIST_PATH, help="Path to the curated titles file"
    )
    args = parser.parse_args()
    asyncio.run(run(args.file))


if __name__ == "__main__":
    main()
