"""Re-fetch every existing game by id from IGDB and upsert, to backfill a
newly-added IGDB-sourced field (e.g. igdb_collections) onto rows added via
enrich_games.py --titles-file's IGDB search path.

Run after adding a new IGDB-sourced column to `models.Game`:

    python -m app.scripts.backfill_igdb_fields

Why this is needed instead of just re-running `sync_igdb --pages N`: that
script's bulk sync is popularity-sorted (IGDB's actual global top N by
rating_count), not "every id already in our `games` table" - once the
catalog includes curated/niche titles pulled in via search (not bulk
pagination), those two sets are NOT the same, so a plain re-sync can
silently miss backfilling them. This script fetches by the exact ids we
already have instead.
"""

import asyncio
import logging

from sqlalchemy import select

from app.db import async_session_factory
from app.models import Game
from app.scripts.sync_igdb import upsert_games
from app.services.igdb_client import IGDBClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 500  # IGDB's own per-request limit


async def run() -> None:
    client = IGDBClient()
    async with async_session_factory() as session:
        result = await session.execute(select(Game.id))
        ids = [row[0] for row in result.all()]
        logger.info("Backfilling IGDB fields for %d games", len(ids))

        for i in range(0, len(ids), BATCH_SIZE):
            batch = ids[i : i + BATCH_SIZE]
            games = await client.fetch_by_ids(batch)
            await upsert_games(session, games)
            logger.info("Backfilled %d/%d", min(i + BATCH_SIZE, len(ids)), len(ids))

        logger.info("Done.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
