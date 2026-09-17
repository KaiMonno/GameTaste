"""Recommendation engine: hard filters (SQL) -> soft-match scoring (in-process).

Per game-recommender-mvp-plan.md section 3. The % match is purely formula-driven
for MVP (not LLM-judged) so it stays auditable and consistent - see "Open Risks" #3
in that doc.
"""

import math

from sqlalchemy import Select, or_, select

from app.models import Game
from app.schemas import HardFilters, SoftPreferences

# Weights for each soft-scoring axis. Tune once real recommendation quality
# feedback comes in - see mvp-plan.md phase 3 ("validates whether the scoring
# logic *feels* right").
#
# review_score is intentionally the lowest weight, not the original 1.0 -
# see the Phase 3.5 popularity fix. It's the only axis included unconditionally
# (every query gets it, whether or not the user asked for it), so at an equal
# or higher weight than an explicitly-requested axis it could silently outrank
# that axis - confirmed concretely with target_popularity: a request for the
# most niche game in the catalog (Shadow of the Colossus, rating_count=375)
# still lost to Witcher 3 GOTY (rating_count=572) purely because Witcher 3's
# quality score (97.6) was higher, even though it's less niche either way.
# review_score now acts as a light tiebreaker, not a co-equal axis.
WEIGHTS = {
    "length": 1.0,
    "review_score": 0.4,
    "popularity": 1.0,
    "story_gameplay": 1.0,
    "similarity": 1.5,
}

# Bounds used to log-normalize rating_count into a 0-100 popularity score when
# a candidate set is too small/uniform to derive relative bounds from itself
# (see _popularity_log_bounds). Wide enough to cover far outside today's
# catalog range (375-5949) so it stays sane as the catalog grows.
FALLBACK_POPULARITY_LOG_MIN = math.log(1)
FALLBACK_POPULARITY_LOG_MAX = math.log(10_000)

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

    # include_genres/exclude_genres match against IGDB genres OR our own
    # LLM-classified custom_categories (Horror, Roguelike, ...) - IGDB has no
    # genre for those, see services/llm_enrichment.py CUSTOM_CATEGORIES. The
    # caller doesn't say which kind a value is; a value just needs to appear
    # in either array.
    if filters.include_genres:
        query = query.where(
            or_(
                Game.genres.overlap(filters.include_genres),
                Game.custom_categories.overlap(filters.include_genres),
            )
        )

    if filters.exclude_genres:
        for genre in filters.exclude_genres:
            query = query.where(~Game.genres.any(genre)).where(~Game.custom_categories.any(genre))

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


def _popularity_log_bounds(games: list[Game]) -> tuple[float, float]:
    """Log-space (min, max) of rating_count across a candidate set, used to
    normalize popularity to 0-100 *relative to what's actually being ranked*
    - e.g. "niche" among an RPG-filtered candidate set means niche relative to
    other RPGs, not to the whole catalog. A plain linear 0-rating_count scale
    doesn't work here: the distribution is heavily right-skewed (catalog p90
    is ~1800 but the max is ~5950), so log-space spreads it out evenly instead
    of compressing nearly every game into the same narrow band.

    Falls back to a wide fixed range when the candidate set is too small or
    too uniform to derive meaningful relative bounds (e.g. a single game, or
    every candidate having identical rating_count).
    """
    counts = [g.igdb_rating_count for g in games if g.igdb_rating_count and g.igdb_rating_count > 0]
    if len(counts) < 2:
        return FALLBACK_POPULARITY_LOG_MIN, FALLBACK_POPULARITY_LOG_MAX

    log_counts = [math.log(c) for c in counts]
    lo, hi = min(log_counts), max(log_counts)
    if hi - lo < 1e-6:
        return FALLBACK_POPULARITY_LOG_MIN, FALLBACK_POPULARITY_LOG_MAX
    return lo, hi


def _normalize_popularity(rating_count: float | None, log_bounds: tuple[float, float]) -> float | None:
    """rating_count -> 0 (most niche in this candidate set) .. 100 (most
    popular). None propagates so _distance_score's "missing data" handling
    still applies rather than treating an unrated game as maximally niche.
    """
    if rating_count is None or rating_count <= 0:
        return None
    log_min, log_max = log_bounds
    if log_max - log_min < 1e-6:
        return 50.0  # every candidate has ~equal popularity - no useful signal either way
    normalized = (math.log(rating_count) - log_min) / (log_max - log_min) * 100
    return max(0.0, min(100.0, normalized))


def score_candidate(
    game: Game, preferences: SoftPreferences, popularity_log_bounds: tuple[float, float] | None = None
) -> float:
    """Weighted soft-match score, normalized to 0-100."""
    axis_scores: dict[str, float] = {}

    if preferences.target_length_hours is not None:
        axis_scores["length"] = _distance_score(game.hltb_main, preferences.target_length_hours, scale=20)

    axis_scores["review_score"] = (game.igdb_rating or 50) / 100

    if preferences.target_popularity is not None:
        popularity = _normalize_popularity(game.igdb_rating_count, popularity_log_bounds or (0.0, 0.0))
        axis_scores["popularity"] = _distance_score(popularity, preferences.target_popularity, scale=50)

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
    # Computed once per request from the actual candidate set (post hard-filter),
    # not the whole catalog - see _popularity_log_bounds.
    popularity_log_bounds = _popularity_log_bounds(games) if preferences.target_popularity is not None else None

    scored = [(game, score_candidate(game, preferences, popularity_log_bounds)) for game in games]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
