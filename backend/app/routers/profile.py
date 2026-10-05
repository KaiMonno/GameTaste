from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Game, User, UserLibraryItem, UserPreferences
from app.schemas import (
    OwnedPlatformsIn,
    OwnedPlatformsOut,
    SteamImportRequest,
    SteamImportResult,
    SteamStatusOut,
    UserPreferencesIn,
    UserPreferencesOut,
)
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


@router.get("/owned-platforms", response_model=OwnedPlatformsOut)
async def get_owned_platforms(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> OwnedPlatformsOut:
    prefs = await db.get(UserPreferences, user.id)
    return OwnedPlatformsOut(owned_platforms=prefs.owned_platforms if prefs is not None else [])


@router.put("/owned-platforms", response_model=OwnedPlatformsOut)
async def save_owned_platforms(
    body: OwnedPlatformsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OwnedPlatformsOut:
    """Deliberately separate from PUT /profile/preferences - that endpoint
    replaces hard_filters/soft_preferences wholesale on every call (see
    save_preferences above), and folding an unrelated field into the same
    request/response shape would mean saving one from one page silently
    clobbers the other's last-saved value unless both pages always
    round-tripped the full state. This only ever touches owned_platforms.
    """
    prefs = await db.get(UserPreferences, user.id)
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)

    prefs.owned_platforms = body.owned_platforms

    await db.commit()
    await db.refresh(prefs)
    return OwnedPlatformsOut(owned_platforms=prefs.owned_platforms)


@router.post("/steam-import", response_model=SteamImportResult)
async def import_steam_library(
    body: SteamImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SteamImportResult:
    """Replaces this user's Steam-sourced library rows with what Steam
    reports right now (delete-then-reinsert, not a merge, but only for
    source="steam" rows) - see models.UserLibraryItem, so a game refunded/
    removed on Steam since the last import stops being excluded from
    recommendations rather than sticking around forever. "manual" rows
    (from the "Already played" button, see mark_as_played) are left
    alone - an earlier version deleted by user_id only, which silently
    wiped out manually-marked games on every re-sync.
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

    await db.execute(
        delete(UserLibraryItem).where(UserLibraryItem.user_id == user.id, UserLibraryItem.source == "steam")
    )

    # A game already excluded via "manual" keeps that row rather than
    # being replaced - the unique (user_id, game_id) constraint means
    # inserting a second row for it would fail outright anyway.
    remaining = await db.execute(select(UserLibraryItem.game_id).where(UserLibraryItem.user_id == user.id))
    already_excluded = {row[0] for row in remaining.all()}

    for appid, playtime in owned:
        game_id = matched_games.get(appid)
        if game_id is not None and game_id not in already_excluded:
            db.add(
                UserLibraryItem(user_id=user.id, game_id=game_id, source="steam", playtime_minutes=playtime)
            )
    await db.commit()

    return SteamImportResult(total_owned=len(owned), matched=len(matched_games), unmatched=len(owned) - len(matched_games))


@router.get("/steam-status", response_model=SteamStatusOut)
async def get_steam_status(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SteamStatusOut:
    """Derived from the library rows themselves (count + most recent
    added_at), not a separate "linked" flag - see SteamStatusOut. The
    frontend polls this on load so "Steam linked" is based on what's
    actually stored, not a one-time toast that's easy to miss or that
    lingers past when it's still accurate - see components/SteamImport.tsx.
    """
    result = await db.execute(
        select(func.count(UserLibraryItem.id), func.max(UserLibraryItem.added_at)).where(
            UserLibraryItem.user_id == user.id
        )
    )
    count, last_synced_at = result.one()
    return SteamStatusOut(linked=count > 0, game_count=count, last_synced_at=last_synced_at)


@router.post("/played/{game_id}", status_code=204)
async def mark_as_played(
    game_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """Excludes a game from this user's future recommendations - the
    manual-marking counterpart to a Steam import (see models.UserLibraryItem
    for why both end up in the same table). A no-op if the game is
    already excluded for any reason (already marked, or Steam-owned) -
    the unique (user_id, game_id) constraint means there's only ever one
    row per game regardless of source.
    """
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")

    existing = await db.execute(
        select(UserLibraryItem).where(UserLibraryItem.user_id == user.id, UserLibraryItem.game_id == game_id)
    )
    if existing.scalar_one_or_none() is not None:
        return

    db.add(UserLibraryItem(user_id=user.id, game_id=game_id, source="manual"))
    await db.commit()


@router.delete("/played/{game_id}", status_code=204)
async def unmark_as_played(
    game_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """Undoes mark_as_played. Removes whatever row exists for this
    (user, game) pair regardless of source - if it happened to be
    Steam-sourced, a future re-sync (routers/profile.py
    import_steam_library) restores it rather than this needing to track
    which source "owns" the exclusion.
    """
    result = await db.execute(
        select(UserLibraryItem).where(UserLibraryItem.user_id == user.id, UserLibraryItem.game_id == game_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return

    await db.delete(item)
    await db.commit()
