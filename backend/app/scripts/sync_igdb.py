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


STEAM_EXTERNAL_GAME_SOURCE = 1  # IGDB external_game_sources.id for "Steam" - confirmed by live query


def _extract_steam_appid(external_games: list[dict] | None) -> int | None:
    """Steam appids are always numeric, but other storefronts' uids aren't
    (Amazon ASINs, GOG hashes, ...) - guard the int() conversion rather than
    assume, even though we only look at entries already filtered to source=1.
    """
    for entry in external_games or []:
        if entry.get("external_game_source") == STEAM_EXTERNAL_GAME_SOURCE:
            try:
                return int(entry["uid"])
            except (KeyError, ValueError, TypeError):
                continue
    return None


async def upsert_games(session, games_page: list[dict]) -> None:
    """Upsert a page of raw IGDB game dicts (as returned by IGDBClient) into
    `games`. Public (not `_`-prefixed) since scripts/enrich_games.py's
    --titles-file flow reuses this too, for the same upsert shape when
    pulling specific titles rather than bulk pages - see that script.
    """
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
            "igdb_category": g.get("game_type"),
            "igdb_collections": _extract_names(g.get("collections")),
            "steam_appid": _extract_steam_appid(g.get("external_games")),
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
            await upsert_games(session, games_page)
            logger.info("Synced %d games (offset %d)", len(games_page), offset)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1, help=f"Number of {PAGE_SIZE}-game pages to sync")
    args = parser.parse_args()
    asyncio.run(sync(args.pages))


if __name__ == "__main__":
    main()
