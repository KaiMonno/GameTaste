import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import GameOut, RecommendationRequest, RecommendationResponse, RecommendationResult
from app.services.llm_explanations import explain_candidates
from app.services.scoring import (
    DIVERSITY_SHORTLIST_SIZE,
    apply_hard_filters,
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
    request: RecommendationRequest, db: AsyncSession = Depends(get_db)
) -> RecommendationResponse:
    """Hard filter -> soft score -> diverse ranked list -> Phase 4 "why
    recommended/why not" blurbs on the final 5 results only (see
    services/llm_explanations.py) - never on the broader 20-candidate
    shortlist or the full catalog.

    Candidates are restricted to the hand-curated list (see
    services/scoring.py restrict_to_curated_list) - the broader IGDB-synced
    catalog is never surfaced here.

    Explanations are best-effort: if the live Claude call fails for any
    reason, the search still returns its 5 numeric results with
    why_recommended/why_not left null rather than failing the whole request -
    the % match (formula-driven, see services/scoring.py) is the part that
    must never depend on a live LLM call succeeding.
    """
    query = restrict_to_curated_list(apply_hard_filters(request.hard_filters))
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
