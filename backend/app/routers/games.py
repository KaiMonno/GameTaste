from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Game
from app.schemas import FacetsOut, GameOut
from app.services.scoring import MOBILE_PLATFORMS

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/facets", response_model=FacetsOut)
async def get_facets(db: AsyncSession = Depends(get_db)) -> FacetsOut:
    """Distinct genres/platforms actually in the catalog, for filter UI options.
    Registered before /{game_id} so "facets" isn't swallowed as a game_id.

    `genres` is IGDB genres unioned with our own custom_categories (Horror,
    Roguelike, ...) into one combined, sorted list - the frontend renders a
    single genre/category picker with no distinction, matching how
    apply_hard_filters matches against both arrays for include/exclude.
    """
    genre_rows = await db.execute(select(func.unnest(Game.genres)).distinct())
    category_rows = await db.execute(select(func.unnest(Game.custom_categories)).distinct())
    genres = sorted({g for (g,) in genre_rows if g} | {c for (c,) in category_rows if c})

    platform_rows = await db.execute(select(func.unnest(Game.platforms)).distinct())
    platforms = sorted({p for (p,) in platform_rows if p and p not in MOBILE_PLATFORMS})

    return FacetsOut(genres=genres, platforms=platforms)


@router.get("/{game_id}", response_model=GameOut)
async def get_game(game_id: int, db: AsyncSession = Depends(get_db)) -> Game:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game
