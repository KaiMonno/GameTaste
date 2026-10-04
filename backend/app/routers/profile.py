from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Game, User, UserLibraryItem, UserPreferences
from app.schemas import SteamImportRequest, SteamImportResult, UserPreferencesIn, UserPreferencesOut
from app.services.auth import get_current_user
from app.services.steam_client import SteamProfileError, get_owned_games, resolve_steam_id64

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


@router.post("/steam-import", response_model=SteamImportResult)
async def import_steam_library(
    body: SteamImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SteamImportResult:
    """Replaces this user's entire library with what Steam reports right
    now (delete-then-reinsert, not a merge) - see models.UserLibraryItem,
    so a game refunded/removed on Steam since the last import stops being
    excluded from recommendations rather than sticking around forever.
    """
    try:
        steam_id64 = await resolve_steam_id64(body.steam_identifier)
        owned = await get_owned_games(steam_id64)
    except SteamProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    appids = [appid for appid, _ in owned]
    matched_games = {}
    if appids:
        result = await db.execute(select(Game.id, Game.steam_appid).where(Game.steam_appid.in_(appids)))
        matched_games = {appid: game_id for game_id, appid in result.all()}

    await db.execute(delete(UserLibraryItem).where(UserLibraryItem.user_id == user.id))
    for appid, playtime in owned:
        game_id = matched_games.get(appid)
        if game_id is not None:
            db.add(
                UserLibraryItem(user_id=user.id, game_id=game_id, source="steam", playtime_minutes=playtime)
            )
    await db.commit()

    return SteamImportResult(total_owned=len(owned), matched=len(matched_games), unmatched=len(owned) - len(matched_games))
