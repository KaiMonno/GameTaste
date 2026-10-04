from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User, UserPreferences
from app.schemas import UserPreferencesIn, UserPreferencesOut
from app.services.auth import get_current_user

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/preferences", response_model=UserPreferencesOut | None)
async def get_preferences(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserPreferences | None:
    """Null when the user has never saved defaults yet - the frontend falls
    back to the filter form's own built-in defaults in that case, same as a
    first-time anonymous visitor.
    """
    return await db.get(UserPreferences, user.id)


@router.put("/preferences", response_model=UserPreferencesOut)
async def save_preferences(
    body: UserPreferencesIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferences:
    prefs = await db.get(UserPreferences, user.id)
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)

    prefs.hard_filters = body.hard_filters.model_dump()
    prefs.soft_preferences = body.soft_preferences.model_dump()

    await db.commit()
    await db.refresh(prefs)
    return prefs
