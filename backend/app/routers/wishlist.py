from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Game, User, WishlistItem
from app.schemas import GameOut, WishlistItemOut
from app.services.auth import get_current_user

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


@router.get("", response_model=list[WishlistItemOut])
async def get_wishlist(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[WishlistItemOut]:
    result = await db.execute(
        select(WishlistItem, Game)
        .join(Game, Game.id == WishlistItem.game_id)
        .where(WishlistItem.user_id == user.id)
        .order_by(WishlistItem.added_at.desc())
    )
    return [WishlistItemOut(game=GameOut.model_validate(game), added_at=item.added_at) for item, game in result.all()]


@router.post("/{game_id}", status_code=204)
async def add_to_wishlist(
    game_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")

    existing = await db.execute(
        select(WishlistItem).where(WishlistItem.user_id == user.id, WishlistItem.game_id == game_id)
    )
    if existing.scalar_one_or_none() is not None:
        return  # already saved - adding twice is a no-op, not an error

    db.add(WishlistItem(user_id=user.id, game_id=game_id))
    await db.commit()


@router.delete("/{game_id}", status_code=204)
async def remove_from_wishlist(
    game_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    result = await db.execute(
        select(WishlistItem).where(WishlistItem.user_id == user.id, WishlistItem.game_id == game_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return  # already absent - removing twice is a no-op, not an error

    await db.delete(item)
    await db.commit()
