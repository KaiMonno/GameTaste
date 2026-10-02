from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import GameOut, RecommendationRequest, RecommendationResponse, RecommendationResult
from app.services.scoring import (
    DIVERSITY_SHORTLIST_SIZE,
    apply_hard_filters,
    rank_candidates,
    restrict_to_curated_list,
    select_diverse_results,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# Fixed, not client-settable: every search shows exactly this many results,
# picked for variety (see select_diverse_results) rather than just the raw
# top N by score.
RESULT_COUNT = 5


@router.post("", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest, db: AsyncSession = Depends(get_db)
) -> RecommendationResponse:
    """Phase 3: hard filter -> soft score -> diverse ranked list, numeric %
    match only. LLM "why/why not" blurbs (phase 4) are not wired in yet -
    see services/llm_explanations.py.

    Candidates are restricted to the hand-curated list (see
    services/scoring.py restrict_to_curated_list) - the broader IGDB-synced
    catalog is never surfaced here.
    """
    query = restrict_to_curated_list(apply_hard_filters(request.hard_filters))
    result = await db.execute(query)
    candidates = list(result.scalars().all())

    ranked = rank_candidates(candidates, request.soft_preferences, DIVERSITY_SHORTLIST_SIZE)
    diverse = select_diverse_results(ranked, RESULT_COUNT)

    return RecommendationResponse(
        results=[
            RecommendationResult(game=GameOut.model_validate(game), match_score=score)
            for game, score in diverse
        ]
    )
