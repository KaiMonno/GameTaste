from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import GameOut, RecommendationRequest, RecommendationResponse, RecommendationResult
from app.services.scoring import apply_hard_filters, rank_candidates

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest, db: AsyncSession = Depends(get_db)
) -> RecommendationResponse:
    """Phase 3: hard filter -> soft score -> ranked list, numeric % match only.
    LLM "why/why not" blurbs (phase 4) are not wired in yet - see
    services/llm_explanations.py.
    """
    query = apply_hard_filters(request.hard_filters)
    result = await db.execute(query)
    candidates = list(result.scalars().all())

    ranked = rank_candidates(candidates, request.soft_preferences, request.limit)

    return RecommendationResponse(
        results=[
            RecommendationResult(game=GameOut.model_validate(game), match_score=score)
            for game, score in ranked
        ]
    )
