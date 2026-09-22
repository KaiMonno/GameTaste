"""Recommendation engine: hard filters (SQL) -> soft-match scoring (in-process).

Per game-recommender-mvp-plan.md section 3. The % match is purely formula-driven
for MVP (not LLM-judged) so it stays auditable and consistent - see "Open Risks" #3
in that doc.

Phase 3.6: IGDB-popularity-as-a-preference was removed entirely (no more
target_popularity soft preference, no more "popularity" scoring axis) - see
mvp-plan.md Phase 3.6 for the full reasoning. It's replaced by a small,
always-on "discovery bias" (DISCOVERY_BIAS_WEIGHT below) that is NOT a user
preference and NOT part of the weighted preference-match formula - it's a
separate, deliberately bounded nudge applied after the match score is
computed, so it can tip a close call toward the less-obvious game but can
never outweigh a genuinely better match. See _discovery_boost.
"""

import math

from sqlalchemy import Select, or_, select

from app.models import Game
from app.schemas import HardFilters, SoftPreferences

# Weights for each soft-scoring axis. Tune once real recommendation quality
# feedback comes in - see mvp-plan.md phase 3 ("validates whether the scoring
# logic *feels* right"). This is *preference match* only - it has nothing to
# do with discovery/niche-ness, see DISCOVERY_BIAS_WEIGHT below for that.
#
# review_score is intentionally a low weight, not 1.0 - see the Phase 3.5
# popularity fix. It's the only axis included unconditionally (every query
# gets it, whether or not the user asked for it), so at an equal or higher
# weight than an explicitly-requested axis it could silently outrank that
# axis - originally confirmed with the now-removed target_popularity axis:
# a request for the most niche game in the catalog (Shadow of the Colossus,
# rating_count=375) still lost to Witcher 3 GOTY (rating_count=572) purely
# because Witcher 3's quality score (97.6) was higher. review_score acts as
# a light tiebreaker, not a co-equal axis.
WEIGHTS = {
    "length": 1.0,
    "review_score": 0.4,
    "story_gameplay": 1.0,
    "similarity": 1.5,
}

# Discovery bias: see the module docstring. This is the ONLY place
# igdb_rating_count still influences ranking - not as a user-settable
# preference, but as a small universal nudge toward less-obvious games.
#
# Why rating_count, chosen over the other signals suggested when this was
# designed (see mvp-plan.md Phase 3.6): IGDB's actual "Popularity Primitives"
# API (want-to-play/wishlist/visit counts) was never synced by this project
# and adding it is new scope; release date isn't synced either (no
# first_release_date column exists) and adding it means a new IGDB field +
# migration + re-sync; a curated "mainstream set" is explicitly what the
# Backloggd Top 100 benchmark must NOT be used for (see scripts/match_backloggd_top100.py).
# rating_count was already being fetched, already log-normalized relative to
# the candidate set from the (now-removed) popularity feature, and is the
# most directly available, explainable proxy for "how many people have
# logged an opinion on this" - not a proxy for quality (igdb_rating is a
# completely separate field/axis, see review_score above).
#
# DISCOVERY_BIAS_WEIGHT is the max match_score points a game can gain purely
# for being the single most niche candidate in its result set (0 points for
# the most mainstream candidate, scaling linearly in between - see
# _discovery_boost). Deliberately small relative to the 0-100 match_score
# range: a game that's a clearly worse preference match (e.g. 70 vs 95, a
# 25-point gap) can never close that gap through niche-ness alone, but two
# close matches (e.g. both ~90) can be tipped toward the more niche one.
DISCOVERY_BIAS_WEIGHT = 6.0

# Bounds used to log-normalize rating_count into a 0-100 "obviousness" score
# when a candidate set is too small/uniform to derive relative bounds from
# itself (see _discovery_log_bounds). Wide enough to cover far outside
# today's catalog range (375-5949) so it stays sane as the catalog grows
# toward the ~190k-game target (see mvp-plan.md section on catalog scale).
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


def _discovery_log_bounds(games: list[Game]) -> tuple[float, float]:
    """Log-space (min, max) of rating_count across a candidate set, used to
    estimate relative "obviousness" *within what's actually being ranked*
    - e.g. niche among an RPG-filtered candidate set means niche relative to
    other RPGs, not to the whole catalog. A plain linear 0-rating_count scale
    doesn't work here: the distribution is heavily right-skewed (catalog p90
    is ~1800 but the max is ~5950), so log-space spreads it out evenly instead
    of compressing nearly every game into the same narrow band.

    Falls back to a wide fixed range when the candidate set is too small or
    too uniform to derive meaningful relative bounds (e.g. a single game, or
    every candidate having identical rating_count) - see DISCOVERY_BIAS_WEIGHT.
    """
    counts = [g.igdb_rating_count for g in games if g.igdb_rating_count and g.igdb_rating_count > 0]
    if len(counts) < 2:
        return FALLBACK_POPULARITY_LOG_MIN, FALLBACK_POPULARITY_LOG_MAX

    log_counts = [math.log(c) for c in counts]
    lo, hi = min(log_counts), max(log_counts)
    if hi - lo < 1e-6:
        return FALLBACK_POPULARITY_LOG_MIN, FALLBACK_POPULARITY_LOG_MAX
    return lo, hi


def _obviousness_score(rating_count: float | None, log_bounds: tuple[float, float]) -> float | None:
    """rating_count -> 0 (least-known game in this candidate set) .. 100
    (best-known). None propagates rather than treating a game with unknown
    rating_count as automatically maximally niche - see _discovery_boost.
    This is a proxy for "how many people have logged an opinion", not for
    quality - igdb_rating/review_score is a completely separate signal.
    """
    if rating_count is None or rating_count <= 0:
        return None
    log_min, log_max = log_bounds
    if log_max - log_min < 1e-6:
        return 50.0  # every candidate is ~equally (un)known - no useful signal either way
    normalized = (math.log(rating_count) - log_min) / (log_max - log_min) * 100
    return max(0.0, min(100.0, normalized))


def _discovery_boost(game: Game, log_bounds: tuple[float, float]) -> float:
    """0 .. DISCOVERY_BIAS_WEIGHT match_score points, higher for less-obvious
    games. A game with unknown rating_count gets 0 boost - missing data
    should never manufacture a discovery advantage.
    """
    obviousness = _obviousness_score(game.igdb_rating_count, log_bounds)
    if obviousness is None:
        return 0.0
    niche_fraction = (100.0 - obviousness) / 100.0
    return niche_fraction * DISCOVERY_BIAS_WEIGHT


def score_candidate(
    game: Game, preferences: SoftPreferences, discovery_log_bounds: tuple[float, float] | None = None
) -> float:
    """0-100 score: a weighted preference-match sub-score, plus a small,
    separately-computed discovery bias added on top (see DISCOVERY_BIAS_WEIGHT
    and the module docstring for why these are kept as two distinct steps
    rather than one axis blended into the weighted average below).
    """
    axis_scores: dict[str, float] = {}

    if preferences.target_length_hours is not None:
        axis_scores["length"] = _distance_score(game.hltb_main, preferences.target_length_hours, scale=20)

    axis_scores["review_score"] = (game.igdb_rating or 50) / 100

    if preferences.target_story_gameplay_ratio is not None:
        axis_scores["story_gameplay"] = _distance_score(
            game.story_gameplay_ratio, preferences.target_story_gameplay_ratio, scale=50
        )

    if preferences.similar_to_game_id is not None:
        axis_scores["similarity"] = 1.0 if preferences.similar_to_game_id in game.similar_game_ids else 0.0

    if axis_scores:
        weighted_sum = sum(axis_scores[axis] * WEIGHTS[axis] for axis in axis_scores)
        total_weight = sum(WEIGHTS[axis] for axis in axis_scores)
        match_score = (weighted_sum / total_weight) * 100
    else:
        match_score = game.igdb_rating or 50

    discovery_boost = _discovery_boost(game, discovery_log_bounds) if discovery_log_bounds else 0.0
    # Clamped, not re-normalized, so DISCOVERY_BIAS_WEIGHT is a real, fixed
    # cap on influence regardless of how the rest of the formula is tuned -
    # a match_score of 100 plus any boost still reads as 100, never higher.
    return round(min(100.0, match_score + discovery_boost), 2)


def rank_candidates(games: list[Game], preferences: SoftPreferences, limit: int) -> list[tuple[Game, float]]:
    # Discovery bias always applies (it's not a user preference - see the
    # module docstring) - computed once per request from the actual
    # candidate set (post hard-filter), not the whole catalog, so "niche"
    # means niche among what's actually being ranked.
    discovery_log_bounds = _discovery_log_bounds(games)

    scored = [(game, score_candidate(game, preferences, discovery_log_bounds)) for game in games]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
