"""Tests for Phase 6: Steam library import (routers/profile.py
import_steam_library) and its effect on /recommendations (excluding
owned games for a signed-in user).

Like test_profile_wishlist.py, calls router functions directly with a
real User row rather than going through FastAPI's dependency injection -
no real Clerk token needed. Unlike that file, the Steam Web API calls
themselves (resolve_steam_id64, get_owned_games) ARE monkeypatched here,
the same way test_recommendations_router.py fakes explain_candidates -
these tests must not depend on a real Steam API key or network access.
"""

import pytest
from sqlalchemy import delete, select

from app.models import Game, User, UserLibraryItem
from app.routers import profile as profile_router
from app.routers import recommendations as recommendations_router
from app.schemas import RecommendationRequest, SteamImportRequest

TEST_CLERK_USER_ID = "test_clerk_user_phase6_steam"


@pytest.fixture
async def test_user(session_factory) -> User:
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.clerk_user_id == TEST_CLERK_USER_ID))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(clerk_user_id=TEST_CLERK_USER_ID)
            session.add(user)
            await session.commit()
            await session.refresh(user)

    try:
        yield user
    finally:
        async with session_factory() as session:
            await session.execute(delete(UserLibraryItem).where(UserLibraryItem.user_id == user.id))
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()


@pytest.fixture
async def matched_game(session_factory):
    """A real game with a steam_appid, so the import's matching logic has
    something real to match against (see backfill_igdb_fields.py).
    """
    async with session_factory() as session:
        result = await session.execute(select(Game.id, Game.steam_appid).where(Game.steam_appid.isnot(None)).limit(1))
        row = result.first()
        if row is None:
            pytest.skip("no game with a steam_appid - run app.scripts.backfill_igdb_fields first")
        return row


async def test_steam_import_matches_and_counts_owned_games(session_factory, monkeypatch, test_user, matched_game):
    game_id, steam_appid = matched_game

    async def fake_resolve(identifier):
        assert identifier == "my-profile"
        return "76561190000000001"

    async def fake_owned_games(steam_id64):
        assert steam_id64 == "76561190000000001"
        return [(steam_appid, 120), (999999999, 5)]  # one matches, one doesn't exist in our catalog

    monkeypatch.setattr(profile_router, "resolve_steam_id64", fake_resolve)
    monkeypatch.setattr(profile_router, "get_owned_games", fake_owned_games)

    async with session_factory() as session:
        result = await profile_router.import_steam_library(
            SteamImportRequest(steam_identifier="my-profile"), user=test_user, db=session
        )

    assert result.total_owned == 2
    assert result.matched == 1
    assert result.unmatched == 1

    async with session_factory() as session:
        rows = await session.execute(select(UserLibraryItem).where(UserLibraryItem.user_id == test_user.id))
        items = rows.scalars().all()
    assert len(items) == 1
    assert items[0].game_id == game_id
    assert items[0].playtime_minutes == 120
    assert items[0].source == "steam"


async def test_steam_import_replaces_rather_than_merges(session_factory, monkeypatch, test_user, matched_game):
    """Re-importing with a smaller owned-games list must drop the games no
    longer owned, not just add to what's already stored.
    """
    game_id, steam_appid = matched_game

    async def fake_resolve(identifier):
        return "76561190000000001"

    async def fake_owned_games_with_game(steam_id64):
        return [(steam_appid, 60)]

    async def fake_owned_games_empty(steam_id64):
        return []

    monkeypatch.setattr(profile_router, "resolve_steam_id64", fake_resolve)

    monkeypatch.setattr(profile_router, "get_owned_games", fake_owned_games_with_game)
    async with session_factory() as session:
        await profile_router.import_steam_library(
            SteamImportRequest(steam_identifier="my-profile"), user=test_user, db=session
        )

    monkeypatch.setattr(profile_router, "get_owned_games", fake_owned_games_empty)
    async with session_factory() as session:
        result = await profile_router.import_steam_library(
            SteamImportRequest(steam_identifier="my-profile"), user=test_user, db=session
        )
    assert result.total_owned == 0

    async with session_factory() as session:
        rows = await session.execute(select(UserLibraryItem).where(UserLibraryItem.user_id == test_user.id))
        items = rows.scalars().all()
    assert items == [], "the previously-owned game should no longer be in the library after re-import"


async def test_recommendations_excludes_owned_games_for_signed_in_user(session_factory, monkeypatch, test_user):
    """The core Phase 6 guarantee: a game in the signed-in user's library
    must not appear in their /recommendations results, but search stays
    unaffected for signed-out users (user=None, unchanged from Phase 5).
    """

    async def no_explanations(games, preferences):
        return {}

    monkeypatch.setattr(recommendations_router, "explain_candidates", no_explanations)

    async with session_factory() as session:
        baseline = await recommendations_router.get_recommendations(RecommendationRequest(), db=session, user=None)
    if not baseline.results:
        pytest.skip("no curated games recommendable - nothing to exclude in this test")
    owned_game_id = baseline.results[0].game.id

    async with session_factory() as session:
        session.add(UserLibraryItem(user_id=test_user.id, game_id=owned_game_id, source="steam"))
        await session.commit()

    async with session_factory() as session:
        excluded = await recommendations_router.get_recommendations(
            RecommendationRequest(), db=session, user=test_user
        )
    assert owned_game_id not in {r.game.id for r in excluded.results}

    async with session_factory() as session:
        still_anonymous = await recommendations_router.get_recommendations(
            RecommendationRequest(), db=session, user=None
        )
    assert owned_game_id in {r.game.id for r in still_anonymous.results}, (
        "excluding for a signed-in user must not affect anonymous search"
    )
