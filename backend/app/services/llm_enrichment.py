"""Phase 2 (+ Phase 3.5 custom categories): offline, cached LLM enrichment -
story/gameplay ratio and custom category classification. Runs once per game
(see scripts/enrich_games.py), not per query.

Bump ENRICHMENT_VERSION and re-run for all games whenever the prompt changes
materially - bumped to 2 for the custom_categories addition, since that's a
new field every previously-enriched game is missing and needs a real Claude
call to fill in (unlike the earlier content_warnings removal, which didn't
need a re-run because the field being dropped didn't touch the field kept).
"""

import json

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game

ENRICHMENT_VERSION = 2

# Controlled taxonomy for custom_categories - IGDB has no genre for these, so
# they're classified here instead. Deliberately a closed list, not
# freeform: Claude is instructed to return only values from this set so the
# recommendation engine's SQL filtering (exact string match against this
# array) stays reliable. Extend this list + bump ENRICHMENT_VERSION if more
# categories are needed later.
CUSTOM_CATEGORIES = [
    "Horror",
    "Roguelike",
    "Roguelite",
    "Soulslike",
    "Metroidvania",
    "CRPG",
    "Immersive Sim",
]

ENRICHMENT_SYSTEM_PROMPT = f"""You are classifying video games for a recommendation engine.
Given a game's title, summary, and IGDB genres, infer:

- story_gameplay_ratio: 0-100 (0 = pure gameplay/mechanics focus, 100 = pure narrative focus)
- custom_categories: zero or more tags from this exact controlled list only -
  {json.dumps(CUSTOM_CATEGORIES)}
  Do not invent categories outside this list. A game can have multiple categories, or none.
  Only include a category you are reasonably confident about from the given information;
  if uncertain whether a category applies, leave it out rather than guessing.

Respond with ONLY a JSON object: {{"story_gameplay_ratio": int, "custom_categories": [string]}}
For story_gameplay_ratio, make your best estimate rather than omitting the field - this is
disclosed to users as "AI-estimated" and reviewed periodically, not treated as ground truth.
"""


class EnrichmentResult:
    def __init__(self, story_gameplay_ratio: int, custom_categories: list[str]):
        self.story_gameplay_ratio = story_gameplay_ratio
        self.custom_categories = custom_categories


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

    # Defense in depth: the prompt constrains Claude to CUSTOM_CATEGORIES, but
    # don't let a model slip-up put an uncontrolled value into the taxonomy -
    # silently drop anything outside the list rather than storing it.
    raw_categories = data.get("custom_categories", [])
    categories = [c for c in raw_categories if c in CUSTOM_CATEGORIES]

    return EnrichmentResult(story_gameplay_ratio=data["story_gameplay_ratio"], custom_categories=categories)
