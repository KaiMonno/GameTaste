from pydantic import BaseModel, ConfigDict


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    summary: str | None
    genres: list[str]
    platforms: list[str]
    game_modes: list[str]
    igdb_rating: float | None
    igdb_rating_count: int | None
    hltb_main: float | None
    hltb_main_extra: float | None
    hltb_completionist: float | None
    story_gameplay_ratio: float | None
    custom_categories: list[str]


class HardFilters(BaseModel):
    """Binary pass/fail filters, applied in SQL before any scoring happens.

    Mobile platforms and DLC/expansions are always excluded - not user-
    configurable, see services/scoring.py apply_hard_filters.
    """

    # Matched against IGDB genres AND our own LLM-classified custom_categories
    # (Horror, Roguelike, ...) - the caller doesn't distinguish between them,
    # see services/scoring.py apply_hard_filters.
    include_genres: list[str] = []
    exclude_genres: list[str] = []
    platforms: list[str] = []
    require_multiplayer: bool = False
    min_review_score: float | None = None


class SoftPreferences(BaseModel):
    """Continuous/ordinal targets used to rank the candidates that survive
    the hard filters. Any field left as None is excluded from scoring.

    No target_popularity field - IGDB popularity is no longer a user-facing
    preference (Phase 3.6). A small, always-on "discovery bias" toward
    less-obvious games is applied automatically to every request instead;
    see services/scoring.py DISCOVERY_BIAS_WEIGHT.
    """

    target_length_hours: float | None = None
    target_story_gameplay_ratio: float | None = None  # 0 (pure gameplay) - 100 (pure story)
    similar_to_game_id: int | None = None


class RecommendationRequest(BaseModel):
    hard_filters: HardFilters = HardFilters()
    soft_preferences: SoftPreferences = SoftPreferences()
    limit: int = 20


class RecommendationResult(BaseModel):
    game: GameOut
    match_score: float  # 0-100, formula-driven (see services/scoring.py)
    why_recommended: str | None = None  # filled in phase 4
    why_not: str | None = None  # filled in phase 4


class RecommendationResponse(BaseModel):
    results: list[RecommendationResult]


class FacetsOut(BaseModel):
    """Distinct genre/platform values actually present in the synced catalog -
    used to populate filter UI options so they never drift from real data.
    `genres` is a union of IGDB genres and our own custom_categories (Horror,
    Roguelike, ...) - the frontend renders one combined list, no distinction.
    Mobile platforms are omitted since they're always excluded server-side
    (see services/scoring.py MOBILE_PLATFORMS) and would be a dead-end filter.
    """

    genres: list[str]
    platforms: list[str]
