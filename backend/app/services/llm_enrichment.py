"""Phase 2: offline, cached LLM enrichment - story/gameplay ratio. Runs once
per game (see scripts/enrich_games.py), not per query.

Bump ENRICHMENT_VERSION and re-run for all games whenever the prompt changes
materially. Not bumped for the content_warnings removal below - the
story_gameplay_ratio values already computed are still correct, no need to
redo 415 Claude calls just to stop asking for a field we no longer store.
"""

import json

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game

ENRICHMENT_VERSION = 1

ENRICHMENT_SYSTEM_PROMPT = """You are rating video games for a recommendation engine.
Given a game's title, summary, genres, and themes, infer:
- story_gameplay_ratio: 0-100 (0 = pure gameplay/mechanics focus, 100 = pure narrative focus)

Respond with ONLY a JSON object: {"story_gameplay_ratio": int}
If you're not confident, make your best estimate rather than omitting the field - this is
disclosed to users as "AI-estimated" and reviewed periodically, not treated as ground truth.
"""


class EnrichmentResult:
    def __init__(self, story_gameplay_ratio: int):
        self.story_gameplay_ratio = story_gameplay_ratio


async def enrich_game(game: Game) -> EnrichmentResult:
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_content = (
        f"Title: {game.name}\n"
        f"Summary: {game.summary or 'N/A'}\n"
        f"Genres: {', '.join(game.genres) or 'N/A'}\n"
    )

    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        system=ENRICHMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    data = json.loads(response.content[0].text)
    return EnrichmentResult(story_gameplay_ratio=data["story_gameplay_ratio"])
