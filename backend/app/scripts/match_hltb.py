"""Phase 1: match games missing HLTB data. Run manually for now:

    python -m app.scripts.match_hltb
"""

import asyncio
import logging

from sqlalchemy import select

from app.db import async_session_factory
from app.models import Game
from app.services.hltb_client import match_game

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run() -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Game).where(Game.hltb_main.is_(None)))
        games = list(result.scalars().all())
        logger.info("Matching HLTB data for %d games", len(games))

        for game in games:
            match = await match_game(game.name)
            if match is None:
                continue
            game.hltb_main = match.main
            game.hltb_main_extra = match.main_extra
            game.hltb_completionist = match.completionist

        await session.commit()
        logger.info("Done.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
