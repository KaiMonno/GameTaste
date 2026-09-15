"""Phase 2: offline, cached LLM enrichment - difficulty, story/gameplay ratio,
content warnings. Runs once per game (see scripts/enrich_games.py), not per query.

Not wired up yet - fill in the prompt once Phase 1 (data foundation) is solid
and you have real IGDB summaries to test against. Bump ENRICHMENT_VERSION and
re-run for all games whenever the prompt changes materially.
"""

import json

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game

ENRICHMENT_VERSION = 1

ENRICHMENT_SYSTEM_PROMPT = """You are rating video games for a recommendation engine.
Given a game's title, summary, genres, and themes, infer:
- difficulty_score: 0-100 (0 = very easy, 100 = very hard)
- story_gameplay_ratio: 0-100 (0 = pure gameplay/mechanics focus, 100 = pure narrative focus)
- content_warnings: short list of strings (e.g. "graphic violence", "gambling themes"), [] if none apparent

Respond with ONLY a JSON object: {"difficulty_score": int, "story_gameplay_ratio": int, "content_warnings": [string]}
If you're not confident, make your best estimate rather than omitting a field - these are
disclosed to users as "AI-estimated" and reviewed periodically, not treated as ground truth.
"""


class EnrichmentResult:
    def __init__(self, difficulty_score: int, story_gameplay_ratio: int, content_warnings: list[str]):
        self.difficulty_score = difficulty_score
        self.story_gameplay_ratio = story_gameplay_ratio
        self.content_warnings = content_warnings


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
    return EnrichmentResult(
        difficulty_score=data["difficulty_score"],
        story_gameplay_ratio=data["story_gameplay_ratio"],
        content_warnings=data["content_warnings"],
    )
