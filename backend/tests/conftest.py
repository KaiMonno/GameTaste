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
"""

from app.models import Game


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
    )
