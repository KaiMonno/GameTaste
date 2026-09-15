"""Phase 2: LLM enrichment batch job. Run manually for now:

    python -m app.scripts.enrich_games

Only processes games with no enrichment yet, or where enrichment_version is
stale - re-running is cheap and safe. Spot-check a sample for accuracy before
trusting this at scale (see mvp-plan.md phase 2).
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.db import async_session_factory
from app.models import Game
from app.services.llm_enrichment import ENRICHMENT_VERSION, enrich_game

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run() -> None:
    async with async_session_factory() as session:
        result = await session.execute(
            select(Game).where(
                or_(Game.enrichment_version.is_(None), Game.enrichment_version < ENRICHMENT_VERSION)
            )
        )
        games = list(result.scalars().all())
        logger.info("Enriching %d games", len(games))

        for game in games:
            try:
                enrichment = await enrich_game(game)
            except Exception:
                logger.exception("Enrichment failed for game %d (%s)", game.id, game.name)
                continue

            game.story_gameplay_ratio = enrichment.story_gameplay_ratio
            game.content_warnings = enrichment.content_warnings
            game.enriched_at = datetime.now(UTC)
            game.enrichment_version = ENRICHMENT_VERSION

            await session.commit()

        logger.info("Done.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
