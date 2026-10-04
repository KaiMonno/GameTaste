"""Shared test fixtures/helpers.

make_game() builds a Game ORM instance directly in memory, without a DB
session. Important gotcha this avoids: mapped_column(..., default=list) is a
SQLAlchemy *client-side default*, only applied at flush/INSERT time - a bare
Game(id=1, name="x") never touches a session in these tests, so any column
relying on that default (genres, platforms, similar_game_ids, ...) would be
None, not [], unless set explicitly here. Getting this wrong doesn't error
loudly - it surfaces later as a confusing `TypeError: argument of type
'NoneType' is not iterable` deep inside scoring.py, so every field the
scoring engine actually reads gets an explicit, real default below.

session_factory is the shared real-DB fixture for integration-style tests -
see its own docstring for why it uses a fresh NullPool engine per test
rather than app.db's module-level singleton.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models import Game


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


def make_game(
    id: int = 1,
    name: str = "Test Game",
    igdb_rating: float | None = 80.0,
    igdb_rating_count: int | None = 1000,
    hltb_main: float | None = None,
    story_gameplay_ratio: float | None = None,
    similar_game_ids: list[int] | None = None,
    genres: list[str] | None = None,
    platforms: list[str] | None = None,
    custom_categories: list[str] | None = None,
    igdb_collections: list[str] | None = None,
) -> Game:
    return Game(
        id=id,
        name=name,
        igdb_rating=igdb_rating,
        igdb_rating_count=igdb_rating_count,
        hltb_main=hltb_main,
        story_gameplay_ratio=story_gameplay_ratio,
        similar_game_ids=similar_game_ids if similar_game_ids is not None else [],
        genres=genres if genres is not None else [],
        platforms=platforms if platforms is not None else [],
        custom_categories=custom_categories if custom_categories is not None else [],
        igdb_collections=igdb_collections if igdb_collections is not None else [],
    )
