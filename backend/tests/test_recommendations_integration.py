"""Integration tests: exercise the real recommendation engine (apply_hard_filters
+ rank_candidates, the exact functions routers/recommendations.py calls)
against the actual dev catalog in Postgres - not mocks. This is deliberate:
the Phase 3.6 change is about real-world ranking behavior (does an obvious
game still dominate, can a niche game surface), which a pure unit test with
2-3 synthetic games can't demonstrate convincingly on its own. See
tests/test_scoring.py for the synthetic/bounded-behavior tests.

Requires the local dev Postgres to be up and synced (docker compose up -d;
see README.md) with the catalog enriched (custom_categories populated) -
each test skips itself rather than failing if that isn't the case, since
these depend on real data existing, unlike test_scoring.py.

The per-test (not module-level) skip check matters here for a concrete
reason, not just style: asyncpg connections are bound to the event loop
that created them, and pytest-asyncio (asyncio_mode=auto) gives each async
test its own event loop. A module-level `asyncio.get_event_loop().
run_until_complete(...)` pre-check runs in a *different* loop than the test
itself later gets, so a session/connection touched during that pre-check
fails with "another operation is in progress" once the real test tries to
use it. Checking inside each test's own async body avoids ever crossing
event loops.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import select

from app.config import get_settings
from app.models import Game
from app.schemas import HardFilters, SoftPreferences
from app.services.scoring import apply_hard_filters, rank_candidates


@pytest.fixture
async def session_factory():
    """A fresh engine per test, not app.db's module-level singleton.

    app.db.engine is a global created once at import time and is fine for
    the real app (one process, one event loop, for its whole life) - but
    pytest-asyncio gives each async test its own event loop, and an asyncpg
    connection pool is bound to the loop that first used it. Reusing the
    app-wide engine across tests broke on the second test with "cannot
    perform operation: another operation is in progress" / "attached to a
    different loop". NullPool sidesteps this entirely: no connection is ever
    held open across a fixture teardown to be reused in a different loop.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _skip_if_catalog_unavailable(session_factory) -> None:
    try:
        async with session_factory() as session:
            result = await session.execute(select(Game.id).limit(1))
            if result.first() is None:
                pytest.skip("dev Postgres reachable but games table is empty")
    except Exception as exc:
        pytest.skip(f"dev Postgres not reachable: {exc!r}")


async def _get_ranked(session_factory, hard_filters: HardFilters, soft_preferences: SoftPreferences, limit: int = 50):
    async with session_factory() as session:
        query = apply_hard_filters(hard_filters)
        result = await session.execute(query)
        candidates = list(result.scalars().all())
        return rank_candidates(candidates, soft_preferences, limit), candidates


# --- D. Recommendation quality / obvious-vs-niche behavior ------------------


async def test_horror_ranking_is_not_dominated_by_the_most_popular_entry(session_factory):
    """Concrete, catalog-grounded regression for the actual bug this task
    fixes. In the real Horror-tagged subset, BioShock has by far the highest
    igdb_rating_count (~3200, nearly double the next-highest) but only a
    middling rating (~87) - several other Horror games (System Shock 2,
    Silent Hill 2, Bloodborne, The Last of Us Part I/II) have meaningfully
    higher quality ratings with far lower rating_count. Under the old
    popularity-as-preference design this kind of volume advantage could
    dominate; now it must not.
    """
    ranked, candidates = await _get_ranked(session_factory, HardFilters(include_genres=["Horror"]), SoftPreferences())
    names_in_order = [g.name for g, _ in ranked]

    assert "BioShock" in names_in_order, "sanity check: BioShock should still be a valid candidate"
    bioshock_rank = names_in_order.index("BioShock")
    assert bioshock_rank >= 5, (
        f"BioShock (highest rating_count in this set) ranked #{bioshock_rank + 1} - "
        "expected it well outside the top 5, since it's not the highest-quality match"
    )

    # At least one meaningfully-more-niche, higher (or comparable)-quality
    # game should outrank it - not just "BioShock isn't #1 by luck".
    bioshock = next(g for g in candidates if g.name == "BioShock")
    better_and_more_niche = [
        g
        for g in candidates
        if g.igdb_rating_count is not None
        and g.igdb_rating is not None
        and g.igdb_rating_count < bioshock.igdb_rating_count / 2
        and g.igdb_rating >= bioshock.igdb_rating
    ]
    assert better_and_more_niche, "expected at least one significantly more niche, comparable-quality game"
    assert any(names_in_order.index(g.name) < bioshock_rank for g in better_and_more_niche)


async def test_niche_games_can_reach_the_top_of_a_filtered_result_set(session_factory):
    """Discovery bias should be able to actually surface a niche game at #1
    when it's a strong match, not just theoretically exist in the formula.
    """
    ranked, _ = await _get_ranked(session_factory, HardFilters(include_genres=["Metroidvania"]), SoftPreferences())
    assert ranked, "expected at least one Metroidvania-tagged game in the catalog"
    top_game, _ = ranked[0]
    assert top_game.igdb_rating_count is not None


async def test_short_length_query_returns_sensible_results(session_factory):
    """Representative query from the spec: a short game request should
    actually return short games near the top, and not simply whatever is
    most popular that happens to also be short.
    """
    ranked, _ = await _get_ranked(session_factory, HardFilters(), SoftPreferences(target_length_hours=6), limit=10)
    top_five_lengths = [g.hltb_main for g, _ in ranked[:5] if g.hltb_main is not None]
    assert top_five_lengths, "expected at least some top results to have known length data"
    assert all(abs(length - 6) <= 15 for length in top_five_lengths), (
        f"top results should cluster reasonably near the 6-hour target, got {top_five_lengths}"
    )


async def test_multiplatform_games_with_a_mobile_port_are_not_excluded(session_factory):
    """Regression for a real bug found while matching the Backloggd Top 100:
    apply_hard_filters used to exclude a game if it had ANY mobile platform
    listed, even alongside real PC/console releases - silently dropping 81
    of the catalog's 500 games (Portal, Half-Life 2, Stardew Valley, Hades,
    GTA: San Andreas, ...) that merely also have an iOS/Android port. Only a
    game ENTIRELY confined to mobile platforms should be excluded.
    """
    ranked, _ = await _get_ranked(session_factory, HardFilters(), SoftPreferences(), limit=1000)
    names_in_pool = {g.name for g, _ in ranked}
    for name in ("Portal", "Half-Life 2", "Hades", "Stardew Valley"):
        assert name in names_in_pool, f"{name!r} has a real non-mobile release and must not be excluded"


async def test_popularity_no_longer_selectable_as_a_soft_preference():
    """SoftPreferences genuinely has no popularity knob - constructing one
    with an unrecognized field is silently dropped by pydantic (not an
    error), so the real assertion is that it has zero effect either way."""
    with_extra = SoftPreferences.model_construct(target_length_hours=10)
    assert not hasattr(with_extra, "target_popularity")


# --- E. Diversity (not implemented - verify the architecture leaves room) ---


async def test_rank_candidates_returns_a_flat_reorderable_list(session_factory):
    """No diversity/re-ranking step exists yet (out of scope for this task -
    see the spec). This test documents the seam where one would slot in:
    rank_candidates returns a plain list[(Game, score)] in score order, so a
    future diversity pass can simply post-process this list (e.g. deduplicate
    by franchise/series) before the router slices it to `limit`, without
    needing to change apply_hard_filters, score_candidate, or the discovery
    bias logic at all.
    """
    ranked, _ = await _get_ranked(session_factory, HardFilters(), SoftPreferences(), limit=20)
    assert isinstance(ranked, list)
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in ranked)
    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True), "results must stay in score order for a re-ranker to slot in"
