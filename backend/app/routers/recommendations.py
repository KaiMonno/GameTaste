import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User, UserLibraryItem, UserPreferences, WishlistItem
from app.schemas import GameOut, RecommendationRequest, RecommendationResponse, RecommendationResult
from app.services.auth import get_current_user_optional
from app.services.llm_explanations import explain_candidates
from app.services.scoring import (
    DIVERSITY_SHORTLIST_SIZE,
    apply_hard_filters,
    exclude_game_ids,
    exclude_unplayable_platforms,
    rank_candidates,
    restrict_to_curated_list,
    select_diverse_results,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# Fixed, not client-settable: every search shows exactly this many results,
# picked for variety (see select_diverse_results) rather than just the raw
# top N by score.
RESULT_COUNT = 5


@router.post("", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> RecommendationResponse:
    """Hard filter -> soft score -> diverse ranked list -> Phase 4 "why
    recommended/why not" blurbs on the final 5 results only (see
    services/llm_explanations.py) - never on the broader 20-candidate
    shortlist or the full catalog.

    Candidates are restricted to the hand-curated list (see
    services/scoring.py restrict_to_curated_list) - the broader IGDB-synced
    catalog is never surfaced here.

    Signed-in is optional, not required (see services/auth.py
    get_current_user_optional) - anonymous search is unaffected. For a
    signed-in user: already-owned/played games (Phase 6) and wishlisted
    games are excluded from candidates before scoring, and so are games
    unplayable on any platform they've set as owned (Phase 7). Wishlisting
    a game means "I already know about this one," so there's no reason to
    keep surfacing it - a game dropped from the wishlist is eligible to be
    recommended again, same as un-marking "already played".

    Explanations are best-effort: if the live Claude call fails for any
    reason, the search still returns its 5 numeric results with
    why_recommended/why_not left null rather than failing the whole request -
    the % match (formula-driven, see services/scoring.py) is the part that
    must never depend on a live LLM call succeeding.
    """
    query = restrict_to_curated_list(apply_hard_filters(request.hard_filters))

    if user is not None:
        owned = await db.execute(select(UserLibraryItem.game_id).where(UserLibraryItem.user_id == user.id))
        query = exclude_game_ids(query, [row[0] for row in owned.all()])

        wishlisted = await db.execute(select(WishlistItem.game_id).where(WishlistItem.user_id == user.id))
        query = exclude_game_ids(query, [row[0] for row in wishlisted.all()])

        prefs = await db.get(UserPreferences, user.id)
        if prefs is not None:
            query = exclude_unplayable_platforms(query, prefs.owned_platforms)

    result = await db.execute(query)
    candidates = list(result.scalars().all())

    ranked = rank_candidates(candidates, request.soft_preferences, DIVERSITY_SHORTLIST_SIZE)
    diverse = select_diverse_results(ranked, RESULT_COUNT)

    explanations: dict[int, tuple[str, str]] = {}
    if diverse:
        try:
            explanations = await explain_candidates([game for game, _ in diverse], request.soft_preferences)
        except Exception:
            logger.exception("explain_candidates failed - returning numeric-only results")

    return RecommendationResponse(
        results=[
            RecommendationResult(
                game=GameOut.model_validate(game),
                match_score=score,
                why_recommended=explanations.get(game.id, (None, None))[0],
                why_not=explanations.get(game.id, (None, None))[1],
            )
            for game, score in diverse
        ]
    )
