"""Tests for Phase 5's profile/wishlist routers. Auth itself (Clerk token
verification, services/auth.py get_current_clerk_user_id) is NOT exercised
here - these call the router functions directly with a real User row
passed in, the same way test_recommendations_router.py calls
get_recommendations directly rather than going through FastAPI's dependency
injection or a live HTTP client. That keeps these tests free and fast
without needing a real Clerk secret key or session token.

Runs against the real dev Postgres (see session_factory in conftest.py),
using a disposable test user cleaned up in a fixture teardown rather than a
fully isolated test database - consistent with this project's existing
integration-test style.
"""

import pytest
from sqlalchemy import delete, select

from app.models import Game, User, UserLibraryItem, UserPreferences, WishlistItem
from app.routers import profile as profile_router
from app.routers import wishlist as wishlist_router
from app.schemas import HardFilters, SoftPreferences, UserPreferencesIn

TEST_CLERK_USER_ID = "test_clerk_user_phase5"


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
            await session.execute(delete(WishlistItem).where(WishlistItem.user_id == user.id))
            await session.execute(delete(UserLibraryItem).where(UserLibraryItem.user_id == user.id))
            await session.execute(delete(UserPreferences).where(UserPreferences.user_id == user.id))
            await session.execute(delete(User).where(User.id == user.id))
            await session.commit()


@pytest.fixture
async def any_game_id(session_factory) -> int:
    async with session_factory() as session:
        result = await session.execute(select(Game.id).limit(1))
        row = result.first()
        if row is None:
            pytest.skip("dev Postgres reachable but games table is empty")
        return row[0]


async def test_preferences_round_trip(session_factory, test_user):
    body = UserPreferencesIn(
        hard_filters=HardFilters(include_genres=["Horror"]),
        soft_preferences=SoftPreferences(target_length_hours=10),
    )

    async with session_factory() as session:
        saved = await profile_router.save_preferences(body, user=test_user, db=session)
    assert saved.hard_filters == {"include_genres": ["Horror"], "exclude_genres": [], "platforms": [], "require_multiplayer": False}

    async with session_factory() as session:
        fetched = await profile_router.get_preferences(user=test_user, db=session)
    assert fetched is not None
    assert fetched.hard_filters["include_genres"] == ["Horror"]
    assert fetched.soft_preferences["target_length_hours"] == 10


async def test_preferences_null_when_never_saved(session_factory, test_user):
    async with session_factory() as session:
        fetched = await profile_router.get_preferences(user=test_user, db=session)
    assert fetched is None


async def test_wishlist_add_list_remove(session_factory, test_user, any_game_id):
    async with session_factory() as session:
        await wishlist_router.add_to_wishlist(any_game_id, user=test_user, db=session)

    async with session_factory() as session:
        items = await wishlist_router.get_wishlist(user=test_user, db=session)
    assert any(item.game.id == any_game_id for item in items)

    async with session_factory() as session:
        await wishlist_router.remove_from_wishlist(any_game_id, user=test_user, db=session)

    async with session_factory() as session:
        items = await wishlist_router.get_wishlist(user=test_user, db=session)
    assert not any(item.game.id == any_game_id for item in items)


async def test_wishlist_add_twice_is_a_no_op(session_factory, test_user, any_game_id):
    async with session_factory() as session:
        await wishlist_router.add_to_wishlist(any_game_id, user=test_user, db=session)
    async with session_factory() as session:
        await wishlist_router.add_to_wishlist(any_game_id, user=test_user, db=session)  # must not raise

    async with session_factory() as session:
        items = await wishlist_router.get_wishlist(user=test_user, db=session)
    matching = [item for item in items if item.game.id == any_game_id]
    assert len(matching) == 1, "adding the same game twice should not create a duplicate row"


async def test_wishlist_remove_when_absent_is_a_no_op(session_factory, test_user, any_game_id):
    async with session_factory() as session:
        await wishlist_router.remove_from_wishlist(any_game_id, user=test_user, db=session)  # must not raise


async def test_mark_as_played_excludes_from_future_recommendations(session_factory, test_user, monkeypatch):
    """Uses a real recommendable (curated) game, not just any row in
    `games` - a non-curated id would never appear in results regardless
    of exclusion, which would make this assertion pass trivially even if
    mark_as_played/exclude_owned_games were broken. Same pattern as
    test_steam_import.py's equivalent test.
    """
    from app.routers import recommendations as recommendations_router
    from app.schemas import RecommendationRequest

    async def no_explanations(games, preferences):
        return {}

    monkeypatch.setattr(recommendations_router, "explain_candidates", no_explanations)

    async with session_factory() as session:
        baseline = await recommendations_router.get_recommendations(RecommendationRequest(), db=session, user=None)
    if not baseline.results:
        pytest.skip("no curated games recommendable - nothing to mark played in this test")
    game_id = baseline.results[0].game.id

    async with session_factory() as session:
        await profile_router.mark_as_played(game_id, user=test_user, db=session)

    async with session_factory() as session:
        items = await session.execute(
            select(UserLibraryItem).where(UserLibraryItem.user_id == test_user.id, UserLibraryItem.game_id == game_id)
        )
        row = items.scalar_one()
    assert row.source == "manual"

    async with session_factory() as session:
        response = await recommendations_router.get_recommendations(
            RecommendationRequest(), db=session, user=test_user
        )
    assert game_id not in {r.game.id for r in response.results}


async def test_mark_as_played_twice_is_a_no_op(session_factory, test_user, any_game_id):
    async with session_factory() as session:
        await profile_router.mark_as_played(any_game_id, user=test_user, db=session)
    async with session_factory() as session:
        await profile_router.mark_as_played(any_game_id, user=test_user, db=session)  # must not raise

    async with session_factory() as session:
        result = await session.execute(
            select(UserLibraryItem).where(UserLibraryItem.user_id == test_user.id, UserLibraryItem.game_id == any_game_id)
        )
        rows = result.scalars().all()
    assert len(rows) == 1, "marking the same game played twice should not create a duplicate row"


async def test_unmark_as_played_removes_the_exclusion(session_factory, test_user, any_game_id):
    async with session_factory() as session:
        await profile_router.mark_as_played(any_game_id, user=test_user, db=session)
    async with session_factory() as session:
        await profile_router.unmark_as_played(any_game_id, user=test_user, db=session)

    async with session_factory() as session:
        result = await session.execute(
            select(UserLibraryItem).where(UserLibraryItem.user_id == test_user.id, UserLibraryItem.game_id == any_game_id)
        )
    assert result.scalar_one_or_none() is None


async def test_unmark_as_played_when_absent_is_a_no_op(session_factory, test_user, any_game_id):
    async with session_factory() as session:
        await profile_router.unmark_as_played(any_game_id, user=test_user, db=session)  # must not raise
