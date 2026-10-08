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

Runs on Haiku, not Sonnet (see anthropic_client.py MODEL_HAIKU) - this is the
one live, user-facing call in the whole app, so its latency is what users
actually feel on every search. The reconciliation task this prompt asks for
is simple enough (connect pre-computed analysis to a stated query, don't
generate new analysis) that the faster/cheaper model is the right fit, not
a quality compromise - verify this holds if the prompt grows more demanding
later.
"""

import json

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game
from app.schemas import SoftPreferences
from app.services.anthropic_client import MODEL_HAIKU, call_claude_json

# These used to be one-line blurbs crammed under each result in a dense
# list (hence a tight 90-char hard cap) - now shown on their own dedicated
# game detail page (app/games/[id]/page.tsx) with real room, so the cap
# only needs to stop a genuinely runaway response, not keep things to a
# single visual line. Still "one short sentence," not a paragraph - the
# prompt's own ask - but it should read as a complete sentence, not get
# chopped mid-thought. Two numbers, not one: the prompt asks for
# PROMPT_TARGET_CHARS, but Haiku treats a character count as a rough target
# rather than a hard rule - observed overshooting a stated hard limit by
# 10-15 chars consistently. Asking for a lower target than what's actually
# enforced leaves room for that overshoot while still landing under
# HARD_MAX_CHARS in the normal case; _enforce_max_length is the real
# guarantee (see below), not the prompt wording.
PROMPT_TARGET_CHARS = 140
HARD_MAX_CHARS = 220

EXPLANATION_SYSTEM_PROMPT = f"""You are writing short, personalized recommendation blurbs for a \
video game recommendation engine.

For each game, you're given its pre-computed analysis (core gameplay loop, tone, narrative style, \
pacing, who it generally suits, standout strengths, common complaints) AND the specific preferences \
this user stated for THIS search. Your job is to connect the two - don't just restate the generic \
analysis, explain how THIS game relates to what THIS user asked for.

Write a "why_recommended" and a "why_not" for each game:
- why_recommended: ONE short sentence, specific to this game and this user's stated preferences. If \
the user gave few or no preferences, draw from the game's standout strengths instead.
- why_not: ONE short sentence, honest about a real mismatch or limitation - from the game's own
  common_complaints/player_fit_mismatch, or a genuine gap versus what the user asked for (e.g. they
  wanted something shorter than this game runs). Don't invent a complaint that isn't true of the game.

Be concise and direct - cut filler words, don't restate the game's name or genre, get straight to the
specific point. A terse fragment beats a full sentence if it's still clear. Respond with ONLY a JSON
array, one object per game in the same order given:
[{{"id": int, "why_recommended": string, "why_not": string}}, ...]
Each string must be under {PROMPT_TARGET_CHARS} characters.
"""


def _enforce_max_length(text: str, max_chars: int = HARD_MAX_CHARS) -> str:
    """Server-side guarantee behind the prompt's PROMPT_TARGET_CHARS ask -
    Haiku treats a stated character count as a target, not a rule, so this
    is what actually keeps every blurb under HARD_MAX_CHARS. Cuts at the
    last word boundary rather than mid-word and appends an ellipsis (counted
    against the limit) so a rare overshoot still reads cleanly.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 1].rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:") + "…"


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
    # blurb-pairs is a small output on its own, especially now that each
    # blurb targets PROMPT_TARGET_CHARS.
    data, _usage, _retried = await call_claude_json(
        client,
        EXPLANATION_SYSTEM_PROMPT,
        user_content,
        model=MODEL_HAIKU,
        max_tokens=150 * len(games) + 1000,
        log_context=f"explain_candidates({len(games)} games)",
    )

    return {
        item["id"]: (_enforce_max_length(item["why_recommended"]), _enforce_max_length(item["why_not"]))
        for item in data
    }
