"""Phase 1: nightly IGDB sync. Run manually for now:

    python -m app.scripts.sync_igdb [--pages N]

Wire this into cron or Celery Beat once the core loop is validated - see
game-recommender-architecture.md section 5/6 for why that's deferred.
"""

import argparse
import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert

from app.db import async_session_factory
from app.models import Game
from app.services.igdb_client import IGDBClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PAGE_SIZE = 500


def _extract_names(items: list[dict] | None) -> list[str]:
    return [item["name"] for item in (items or [])]


async def _upsert_page(session, games_page: list[dict]) -> None:
    if not games_page:
        return

    rows = [
        {
            "id": g["id"],
            "name": g["name"],
            "summary": g.get("summary"),
            "genres": _extract_names(g.get("genres")),
            "platforms": _extract_names(g.get("platforms")),
            "game_modes": _extract_names(g.get("game_modes")),
            "igdb_rating": g.get("rating"),
            "igdb_rating_count": g.get("rating_count"),
            "similar_game_ids": g.get("similar_games", []),
        }
        for g in games_page
    ]

    stmt = insert(Game).values(rows)
    update_cols = {col: stmt.excluded[col] for col in rows[0] if col != "id"}
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)

    await session.execute(stmt)
    await session.commit()


async def sync(pages: int) -> None:
    client = IGDBClient()
    async with async_session_factory() as session:
        for page in range(pages):
            offset = page * PAGE_SIZE
            games_page = await client.fetch_games(offset=offset, limit=PAGE_SIZE)
            if not games_page:
                logger.info("No more games at offset %d, stopping.", offset)
                break
            await _upsert_page(session, games_page)
            logger.info("Synced %d games (offset %d)", len(games_page), offset)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1, help=f"Number of {PAGE_SIZE}-game pages to sync")
    args = parser.parse_args()
    asyncio.run(sync(args.pages))


if __name__ == "__main__":
    main()
