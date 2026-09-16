"""Recommendation engine: hard filters (SQL) -> soft-match scoring (in-process).

Per game-recommender-mvp-plan.md section 3. The % match is purely formula-driven
for MVP (not LLM-judged) so it stays auditable and consistent - see "Open Risks" #3
in that doc.
"""

from sqlalchemy import Select, or_, select

from app.models import Game
from app.schemas import HardFilters, SoftPreferences

# Weights for each soft-scoring axis. Tune once real recommendation quality
# feedback comes in - see mvp-plan.md phase 3 ("validates whether the scoring
# logic *feels* right").
WEIGHTS = {
    "length": 1.0,
    "review_score": 1.0,
    "popularity": 0.5,
    "story_gameplay": 1.0,
    "similarity": 1.5,
}

# Platforms always excluded, not user-configurable. Beyond the two obvious
# ones, IGDB's platform list also includes older phone-era platforms that are
# just as much "mobile" - left out of a first pass, added after noticing them
# still showing up in games.platforms / the facets filter list.
MOBILE_PLATFORMS = ["Android", "iOS", "Windows Phone", "Windows Mobile", "Legacy Mobile Device", "N-Gage"]

# IGDB `category` values that mean "not a standalone game" - dlc_addon (1) and
# expansion (2). Always excluded, not user-configurable. Rows synced before
# `category` was tracked have igdb_category = None and are kept rather than
# dropped (unknown is treated as "main game", not as DLC).
DLC_CATEGORIES = [1, 2]


def apply_hard_filters(filters: HardFilters) -> Select:
    """Build the SQL query that reduces the catalog to a candidate set.
    Binary pass/fail only - no scoring here.
    """
    query = select(Game)

    for platform in MOBILE_PLATFORMS:
        query = query.where(~Game.platforms.any(platform))

    query = query.where(or_(Game.igdb_category.is_(None), Game.igdb_category.not_in(DLC_CATEGORIES)))

    if filters.include_genres:
        query = query.where(Game.genres.overlap(filters.include_genres))

    if filters.exclude_genres:
        for genre in filters.exclude_genres:
            query = query.where(~Game.genres.any(genre))

    if filters.platforms:
        query = query.where(Game.platforms.overlap(filters.platforms))

    if filters.require_multiplayer:
        query = query.where(Game.game_modes.any("Multiplayer"))

    if filters.min_review_score is not None:
        query = query.where(Game.igdb_rating >= filters.min_review_score)

    return query


def _distance_score(value: float | None, target: float | None, scale: float) -> float:
    """1.0 = exact match, decaying toward 0 as |value - target| grows past `scale`.
    Returns a neutral 0.5 when either side is missing data, so missing enrichment
    doesn't zero out a game's score outright.
    """
    if value is None or target is None:
        return 0.5
    distance = abs(value - target)
    return max(0.0, 1.0 - distance / scale)


def score_candidate(game: Game, preferences: SoftPreferences) -> float:
    """Weighted soft-match score, normalized to 0-100."""
    axis_scores: dict[str, float] = {}

    if preferences.target_length_hours is not None:
        axis_scores["length"] = _distance_score(game.hltb_main, preferences.target_length_hours, scale=20)

    axis_scores["review_score"] = (game.igdb_rating or 50) / 100

    if preferences.target_popularity is not None:
        axis_scores["popularity"] = _distance_score(
            game.igdb_rating_count, preferences.target_popularity, scale=5000
        )

    if preferences.target_story_gameplay_ratio is not None:
        axis_scores["story_gameplay"] = _distance_score(
            game.story_gameplay_ratio, preferences.target_story_gameplay_ratio, scale=50
        )

    if preferences.similar_to_game_id is not None:
        axis_scores["similarity"] = 1.0 if preferences.similar_to_game_id in game.similar_game_ids else 0.0

    if not axis_scores:
        return round((game.igdb_rating or 50), 2)

    weighted_sum = sum(axis_scores[axis] * WEIGHTS[axis] for axis in axis_scores)
    total_weight = sum(WEIGHTS[axis] for axis in axis_scores)
    return round((weighted_sum / total_weight) * 100, 2)


def rank_candidates(games: list[Game], preferences: SoftPreferences, limit: int) -> list[tuple[Game, float]]:
    scored = [(game, score_candidate(game, preferences)) for game in games]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
