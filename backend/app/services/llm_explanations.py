"""Phase 4: online, per-query "why you'll like it / why you might not" blurbs.

Called on the top ~15-20 scored candidates only, in a single batched call -
never per-candidate and never on the full catalog. The % match itself is NOT
generated here; it comes from services/scoring.py so ranking stays auditable
(see mvp-plan.md "Open Risks" #3). Not wired into the /recommendations route
yet - phase 3 ships numeric-only results first.
"""

import json

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game
from app.schemas import SoftPreferences

EXPLANATION_SYSTEM_PROMPT = """You are explaining video game recommendations to a user.
For each game given, write a short "why you'll like it" and "why you might not" based on
how well it matches the user's stated preferences. Be specific to the game, not generic.

Respond with ONLY a JSON array, one object per game in the same order given:
[{"id": int, "why_recommended": string, "why_not": string}, ...]
Keep each string under 200 characters.
"""


async def explain_candidates(
    games: list[Game], preferences: SoftPreferences
) -> dict[int, tuple[str, str]]:
    """Returns {game_id: (why_recommended, why_not)}."""
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    candidates_payload = [
        {
            "id": game.id,
            "name": game.name,
            "summary": game.summary,
            "genres": game.genres,
            "hltb_main": game.hltb_main,
            "story_gameplay_ratio": game.story_gameplay_ratio,
        }
        for game in games
    ]

    user_content = (
        f"User preferences: {preferences.model_dump_json()}\n\n"
        f"Candidates: {json.dumps(candidates_payload)}"
    )

    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=200 * len(games) + 200,
        system=EXPLANATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    parsed = json.loads(response.content[0].text)
    return {item["id"]: (item["why_recommended"], item["why_not"]) for item in parsed}
