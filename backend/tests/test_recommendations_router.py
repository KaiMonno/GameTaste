"""Tests for the Phase 4 wiring in routers/recommendations.py - specifically
that a live Claude failure degrades gracefully (numeric results still come
back) rather than taking the whole search down, and that a successful
explanation correctly merges onto the matching game.

Deliberately does NOT call the real Claude API - explain_candidates is
monkeypatched, so these run free and fast while still exercising the real
router function against the real dev catalog (not a mocked DB too; only the
LLM call is faked, matching this project's general preference for testing
against real data where that's cheap - see
test_recommendations_integration.py's docstring for why).
"""

import pytest

from app.routers import recommendations as recommendations_router
from app.schemas import HardFilters, RecommendationRequest, SoftPreferences


@pytest.fixture(autouse=True)
async def _skip_if_catalog_unavailable(session_factory) -> None:
    from sqlalchemy import select

    from app.models import Game

    try:
        async with session_factory() as session:
            result = await session.execute(select(Game.id).limit(1))
            if result.first() is None:
                pytest.skip("dev Postgres reachable but games table is empty")
    except Exception as exc:
        pytest.skip(f"dev Postgres not reachable: {exc!r}")


async def test_explanation_failure_still_returns_numeric_results(session_factory, monkeypatch):
    """The core resilience guarantee: match_score and game data must never
    depend on a live LLM call succeeding. If explain_candidates raises for
    any reason, the search should still return its results, just with
    why_recommended/why_not left null.
    """

    async def _always_fails(games, preferences):
        raise RuntimeError("simulated Claude failure")

    monkeypatch.setattr(recommendations_router, "explain_candidates", _always_fails)

    async with session_factory() as session:
        response = await recommendations_router.get_recommendations(RecommendationRequest(), db=session)

    assert len(response.results) > 0, "expected at least one curated game to be recommendable"
    for result in response.results:
        assert result.match_score is not None
        assert result.why_recommended is None
        assert result.why_not is None


async def test_explanations_merge_onto_the_correct_games(session_factory, monkeypatch):
    """A successful explain_candidates result must be matched to the right
    game by id, not by list position - guards against a silent off-by-one
    if the LLM ever reorders its response relative to what was asked.
    """
    captured_ids: list[int] = []

    async def _fake_explanations(games, preferences):
        captured_ids.extend(game.id for game in games)
        # Deliberately return in REVERSED order from what was asked, to
        # prove the router matches by id, not position.
        return {game.id: (f"why-{game.id}", f"why-not-{game.id}") for game in reversed(games)}

    monkeypatch.setattr(recommendations_router, "explain_candidates", _fake_explanations)

    async with session_factory() as session:
        response = await recommendations_router.get_recommendations(RecommendationRequest(), db=session)

    assert captured_ids, "expected explain_candidates to be called with the final result set"
    for result in response.results:
        assert result.why_recommended == f"why-{result.game.id}"
        assert result.why_not == f"why-not-{result.game.id}"


async def test_hard_filters_still_apply_with_explanations_wired_in(session_factory, monkeypatch):
    """Regression guard: Phase 4 wiring must not have disturbed the existing
    hard-filter/diversity pipeline - a genre filter should still narrow
    results the same way it did before this change.
    """

    async def _no_explanations(games, preferences):
        return {}

    monkeypatch.setattr(recommendations_router, "explain_candidates", _no_explanations)

    request = RecommendationRequest(
        hard_filters=HardFilters(include_genres=["Horror"]),
        soft_preferences=SoftPreferences(),
    )

    async with session_factory() as session:
        response = await recommendations_router.get_recommendations(request, db=session)

    for result in response.results:
        has_horror_genre = "Horror" in result.game.genres
        has_horror_category = "Horror" in result.game.custom_categories
        assert has_horror_genre or has_horror_category, (
            f"{result.game.name!r} matched a Horror filter but has neither the genre nor the category"
        )
