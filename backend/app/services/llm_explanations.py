"""Phase 4: online, per-query "why you'll like it / why you might not" blurbs.

Called on the final diverse result set only (5 games, see
routers/recommendations.py RESULT_COUNT) in a single batched call - never
per-candidate and never on the broader shortlist/catalog. The % match itself
is NOT generated here; it comes from services/scoring.py so ranking stays
auditable (see mvp-plan.md "Open Risks" #3).

This call is grounded in the v3 enrichment fields (core_loop, tone_atmosphere,
player_fit, standout_strengths, common_complaints, ...) already computed
offline per game - Claude isn't asked to analyze each game from scratch here,
only to reconcile analysis it already has with what *this specific query*
asked for. That's what keeps a 5-game batched call cheap and fast despite
being live: the hard analytical work happened once, offline, per game; this
call's job is just personalization.
"""

import json

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game
from app.schemas import SoftPreferences
from app.services.anthropic_client import call_claude_json

EXPLANATION_SYSTEM_PROMPT = """You are writing short, personalized recommendation blurbs for a \
video game recommendation engine.

For each game, you're given its pre-computed analysis (core gameplay loop, tone, narrative style, \
pacing, who it generally suits, standout strengths, common complaints) AND the specific preferences \
this user stated for THIS search. Your job is to connect the two - don't just restate the generic \
analysis, explain how THIS game relates to what THIS user asked for.

Write a "why_recommended" and a "why_not" for each game:
- why_recommended: 1-2 sentences, specific to this game and this user's stated preferences. If the \
user gave few or no preferences, draw from the game's standout strengths instead.
- why_not: 1-2 sentences, honest about a real mismatch or limitation - from the game's own
  common_complaints/player_fit_mismatch, or a genuine gap versus what the user asked for (e.g. they
  wanted something shorter than this game runs). Don't invent a complaint that isn't true of the game.

Respond with ONLY a JSON array, one object per game in the same order given:
[{"id": int, "why_recommended": string, "why_not": string}, ...]
Keep each string under 220 characters.
"""


def _candidate_payload(game: Game) -> dict:
    return {
        "id": game.id,
        "name": game.name,
        "genres": game.genres,
        "custom_categories": game.custom_categories,
        "hltb_main": game.hltb_main,
        "story_gameplay_ratio": game.story_gameplay_ratio,
        "pacing_score": game.pacing_score,
        "mechanical_execution_focus": game.mechanical_execution_focus,
        "core_loop": game.core_loop,
        "tone_atmosphere": game.tone_atmosphere,
        "narrative_style": game.narrative_style,
        "player_fit": game.player_fit,
        "player_fit_mismatch": game.player_fit_mismatch,
        "standout_strengths": game.standout_strengths,
        "common_complaints": game.common_complaints,
    }


async def explain_candidates(games: list[Game], preferences: SoftPreferences) -> dict[int, tuple[str, str]]:
    """Returns {game_id: (why_recommended, why_not)}. Raises on failure (both
    the normal attempt and its one automatic retry) - callers in the live
    request path must decide how to degrade (see routers/recommendations.py,
    which treats this as best-effort and still returns numeric results if
    this raises, rather than failing the whole search over an explanation).
    """
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    candidates_payload = [_candidate_payload(game) for game in games]

    user_content = (
        f"This user's stated preferences for this search: {preferences.model_dump_json()}\n\n"
        f"Candidates: {json.dumps(candidates_payload)}"
    )

    # max_tokens scales a little with game count but mostly just needs
    # headroom for extended thinking (see anthropic_client.py) - 5 short
    # blurb-pairs is a small output on its own.
    data, _usage, _retried = await call_claude_json(
        client,
        EXPLANATION_SYSTEM_PROMPT,
        user_content,
        max_tokens=400 * len(games) + 1500,
        log_context=f"explain_candidates({len(games)} games)",
    )

    return {item["id"]: (item["why_recommended"], item["why_not"]) for item in data}
