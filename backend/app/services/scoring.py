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

from app.models import CuratedListGame, Game
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

# Platforms that make a game "mobile" for exclusion purposes, not user-
# configurable. Beyond the two obvious ones, IGDB's platform list also
# includes older phone-era platforms that are just as much "mobile" - left
# out of a first pass, added after noticing them still showing up in
# games.platforms / the facets filter list.
#
# IMPORTANT: a game is only excluded if EVERY platform it has is in this
# list (see apply_hard_filters) - not if it merely has one of these among
# several. Originally implemented as "exclude if platforms contains ANY of
# these", which silently dropped 81 of the catalog's 500 games (Portal,
# Half-Life 2, Stardew Valley, Hades, GTA: San Andreas, ...) purely for
# having an incidental mobile port alongside their real PC/console release -
# discovered while matching the Backloggd Top 100, where it caused several
# genuinely-catalogued games (Hades among them) to come back "unmatched"
# because they weren't in the candidate pool at all. Confirmed via the
# actual data before fixing: only 1 game in the whole catalog is genuinely
# mobile-only under the corrected definition.
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

    # Exclude only games that are ENTIRELY confined to mobile platforms
    # (platforms is a subset of MOBILE_PLATFORMS) - a game with a mobile
    # port alongside its real PC/console release must not be excluded just
    # for having that port. Games with no platform data at all (empty
    # array) are kept rather than penalized for missing data, consistent
    # with how the rest of this module treats missing enrichment.
    query = query.where(
        or_(Game.platforms == [], ~Game.platforms.contained_by(MOBILE_PLATFORMS))
    )

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

    return query


def restrict_to_curated_list(query: Select) -> Select:
    """Scope a games query to the hand-curated recommendation set (see
    models.CuratedListGame / the repo-root `Game List` file) - a game not in
    this set is never a recommendation candidate, no matter what it scores.

    Deliberately kept separate from apply_hard_filters rather than folded
    into it: apply_hard_filters is also reused by
    scripts/match_backloggd_top100.py and scripts/enrich_games.py's
    --titles-file mode to check filter-exclusion correctness (mobile/DLC/
    genre/platform) against the FULL games table, independent of which
    titles happen to be curated right now - those callers must NOT be
    silently narrowed to the curated set too.
    """
    return query.join(CuratedListGame, CuratedListGame.game_id == Game.id)


def exclude_owned_games(query: Select, owned_game_ids: list[int]) -> Select:
    """Phase 6: drop a signed-in user's already-owned (Steam-imported)
    games from the candidate set - see routers/recommendations.py, which
    only calls this when there's a signed-in user with a non-empty
    library. A no-op for an empty list rather than an always-true/no-op
    SQL clause, since `Game.id.not_in([])` is valid but pointless to add.
    """
    if not owned_game_ids:
        return query
    return query.where(Game.id.not_in(owned_game_ids))


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


# How many of the best-matching candidates select_diverse_results is allowed
# to choose among - generous enough to give real variety to pick from, but
# small enough that diversity never reaches into mediocre matches just for
# novelty. Mirrors mvp-plan.md's existing "top ~15-20 candidates" convention
# used elsewhere in the plan for the same reason (a bounded shortlist, not
# the whole candidate pool).
DIVERSITY_SHORTLIST_SIZE = 20

# match_score-equivalent points subtracted from a candidate for having
# maximal (1.0) genre/category overlap with an already-selected result,
# scaling down to 0 at no overlap. Large enough to meaningfully space out a
# small result page, but a genuinely much-better match (e.g. 95 vs 60) still
# wins - diversity is a tiebreaker among good matches, same spirit as
# DISCOVERY_BIAS_WEIGHT, not a way to force an unrelated genre into the
# results regardless of fit. Needs tuning once real feedback comes in, same
# as WEIGHTS.
DIVERSITY_PENALTY_WEIGHT = 30.0


def _similarity(a: Game, b: Game) -> float:
    """0 (unrelated) to 1 (maximally similar) - the signal
    select_diverse_results uses for "how similar are these two games".

    Two games sharing an IGDB collection (direct series - e.g. Risk of Rain,
    Risk of Rain 2, and Risk of Rain Returns all share collection "Risk of
    Rain") are treated as maximally similar outright, regardless of genre
    overlap - a real case found in testing: two same-franchise games with
    near-top scores both made the result page because their *genre* tags,
    while identical, only capped the penalty at the same level as any other
    same-genre pair, and nothing else scored close enough to outrank the
    second one anyway. Franchise sameness is a much stronger "too similar to
    both show" signal than genre overlap and needs to dominate it, not just
    add to it.

    Otherwise, falls back to genre/custom_categories tag-set overlap
    (Jaccard) - the most legible "what kind of game is this" data already in
    the schema; a proper embedding-based similarity is a v2 upgrade
    (architecture.md section 6), not this.
    """
    if set(a.igdb_collections) & set(b.igdb_collections):
        return 1.0

    tags_a = set(a.genres) | set(a.custom_categories)
    tags_b = set(b.genres) | set(b.custom_categories)
    union = tags_a | tags_b
    if not union:
        return 0.0
    return len(tags_a & tags_b) / len(union)


def select_diverse_results(ranked: list[tuple[Game, float]], limit: int) -> list[tuple[Game, float]]:
    """Greedy diversity selection (maximal marginal relevance) over an
    already-scored, already-sorted candidate list: picks `limit` results,
    each the best remaining match penalized by how similar (genre/category
    overlap) it is to what's already been picked - so a small result page
    isn't several near-identical roguelikes just because the catalog has
    several near-identical roguelikes that all score well.

    Deliberately NOT inside rank_candidates - that function stays a plain
    score-sorted list (see test_rank_candidates_returns_a_flat_reorderable_
    list) so this can be a separate post-processing step the router applies,
    without touching apply_hard_filters, score_candidate, or discovery bias.

    `ranked` must already be in score-sorted order (rank_candidates' output)
    and is restricted here to the top DIVERSITY_SHORTLIST_SIZE before
    selecting - diversity only ever trades among the already-strongest
    matches, never reaches into weak ones for novelty.
    """
    shortlist = ranked[:DIVERSITY_SHORTLIST_SIZE]
    if not shortlist:
        return []

    selected = [shortlist[0]]
    remaining = shortlist[1:]

    while len(selected) < limit and remaining:
        def penalized_score(candidate: tuple[Game, float]) -> float:
            game, match_score = candidate
            max_similarity = max(_similarity(game, picked) for picked, _ in selected)
            return match_score - max_similarity * DIVERSITY_PENALTY_WEIGHT

        best = max(remaining, key=penalized_score)
        selected.append(best)
        remaining.remove(best)

    return selected
