"""Phase 2 (+ Phase 3.5 custom categories, + v3 richer analysis): offline,
cached LLM enrichment. Runs once per game (see scripts/enrich_games.py), not
per query.

Bump ENRICHMENT_VERSION and re-run for all games whenever the prompt changes
materially - bumped to 3 for the v3 field set below, since every existing
row is missing these new fields and needs a real Claude call to fill them
in. Note this marks the existing 415 games' enrichment as stale; re-running
them is a separate, later decision, not part of whatever run bumped this.
"""

import json
import logging

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.models import Game

logger = logging.getLogger(__name__)

ENRICHMENT_VERSION = 3

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

# v3: richer per-game analysis, for Phase 4 explanations and future scoring
# axes - see models.py Game for the full rationale on each field and why
# difficulty/content-warnings stay excluded. Structured fields use the same
# 0-100 pattern as story_gameplay_ratio; free text/list fields are for
# explanations only, never fed into the formula-driven match score.
ENRICHMENT_SYSTEM_PROMPT = f"""You are analyzing a video game for a recommendation engine aimed at \
enthusiast players who want genuinely good matches, including games they haven't heard of.

Given a game's title, summary, IGDB genres, and (if known) its main-story length in hours, infer:

- story_gameplay_ratio: 0-100 (0 = pure gameplay/mechanics focus, 100 = pure narrative focus)
- custom_categories: zero or more tags from this exact controlled list only -
  {json.dumps(CUSTOM_CATEGORIES)}
  Do not invent categories outside this list. A game can have multiple categories, or none.
  Only include a category you are reasonably confident about from the given information;
  if uncertain whether a category applies, leave it out rather than guessing.
- pacing_score: 0-100 (0 = slow/methodical, 100 = fast/frenetic)
- mechanical_execution_focus: 0-100 (0 = cerebral/strategic/narrative-driven, 100 = reflex/execution-driven).
  This is NOT a difficulty rating - it describes what KIND of skill the game rewards
  (twitch reflexes and precision vs. planning and judgment), not how hard the game is to succeed at.
  Do not let perceived difficulty influence this value.
- core_loop: 1-2 sentences on the moment-to-moment gameplay loop
- tone_atmosphere: a short phrase or sentence on tone/atmosphere
- narrative_style: a short phrase or sentence on how the story is told (e.g. linear cinematic,
  environmental/found narrative, branching dialogue-driven, minimal/no story)
- player_fit: 1 sentence on what kind of player this suits
- player_fit_mismatch: 1 sentence on what kind of player it will NOT suit
- standout_strengths: 2-4 short strings, this game's standout strengths
- common_complaints: 2-4 short strings, common DESIGN/GAMEPLAY criticism (e.g. "combat gets
  repetitive", "slow opening hours") - NOT content warnings or sensitive-content flags, which
  are out of scope entirely; do not mention violence, disturbing content, or similar here.
- comparable_games: 2-5 short strings, other game titles this is genuinely comparable to

Respond with ONLY a JSON object with exactly these keys: {{"story_gameplay_ratio": int, \
"custom_categories": [string], "pacing_score": int, "mechanical_execution_focus": int, \
"core_loop": string, "tone_atmosphere": string, "narrative_style": string, "player_fit": string, \
"player_fit_mismatch": string, "standout_strengths": [string], "common_complaints": [string], \
"comparable_games": [string]}}

For all numeric/required fields, make your best estimate rather than omitting the field - this
analysis is disclosed to users as "AI-estimated" and reviewed periodically, not treated as ground
truth.
"""


class EnrichmentResult:
    def __init__(
        self,
        story_gameplay_ratio: int,
        custom_categories: list[str],
        pacing_score: int,
        mechanical_execution_focus: int,
        core_loop: str,
        tone_atmosphere: str,
        narrative_style: str,
        player_fit: str,
        player_fit_mismatch: str,
        standout_strengths: list[str],
        common_complaints: list[str],
        comparable_games: list[str],
        usage: dict,
        retried: bool = False,
    ):
        self.story_gameplay_ratio = story_gameplay_ratio
        self.custom_categories = custom_categories
        self.pacing_score = pacing_score
        self.mechanical_execution_focus = mechanical_execution_focus
        self.core_loop = core_loop
        self.tone_atmosphere = tone_atmosphere
        self.narrative_style = narrative_style
        self.player_fit = player_fit
        self.player_fit_mismatch = player_fit_mismatch
        self.standout_strengths = standout_strengths
        self.common_complaints = common_complaints
        self.comparable_games = comparable_games
        # Raw usage dict from the Anthropic response (input_tokens,
        # output_tokens, and cache fields if present) - see
        # scripts/enrich_games.py for how this feeds cost reporting.
        self.usage = usage
        # True if the first attempt failed and this result came from an
        # automatic retry - see enrich_game(). Surfaced so callers/reports
        # can track how often that happens, not just that it recovered.
        self.retried = retried


async def _call_once(client: AsyncAnthropic, user_content: str) -> tuple[dict, dict]:
    """One API call + parse attempt. Returns (parsed_json, usage_dict).

    max_tokens is 2000, not the ~300-800 the simpler pre-v3 prompt used -
    root-caused a real failure mode during testing: Sonnet 5 does internal
    extended thinking on this prompt by default, and that thinking counts
    against max_tokens. One observed failure had 670 of an 800 max_tokens
    budget consumed by thinking alone (usage.output_tokens_details.
    thinking_tokens), leaving no room for the actual JSON and truncating the
    response with stop_reason="max_tokens".

    Scans ALL of response.content for the text block instead of assuming
    it's response.content[0] - a second, more common real bug found running
    the full list: when extended thinking is used, response.content[0] is a
    *thinking* block (no `.text`), and the actual answer is content[1]. The
    old index-0-only check misread this as an empty response on ~9% of
    calls (stop_reason="end_turn", content_blocks=2, real thinking_tokens
    consumed, genuine JSON sitting right there in block 1) - every one of
    those was a wasted retry, or in ~10% of cases a real failure, purely
    from not looking at the right content block, not an API problem.
    """
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        system=ENRICHMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    usage = response.usage.model_dump() if response.usage else {}

    text_block = next((block for block in response.content if getattr(block, "type", None) == "text"), None)

    if text_block is None or not text_block.text:
        raise ValueError(
            f"No text content block in response (stop_reason={response.stop_reason!r}, "
            f"content_block_types={[getattr(b, 'type', None) for b in response.content]}, usage={usage})"
        )

    return json.loads(_strip_markdown_fence(text_block.text)), usage


def _strip_markdown_fence(text: str) -> str:
    """The system prompt says "respond with ONLY a JSON object", but Claude
    still occasionally wraps the answer in a ```json ... ``` fence anyway
    (observed reproducibly for at least one real game during enrichment -
    'Limbo', stop_reason="end_turn", otherwise well-formed JSON inside the
    fence). json.loads on a string starting with a backtick fails immediately
    with "Expecting value: line 1 column 1 (char 0)", which is
    indistinguishable from a genuinely empty response unless you go look -
    strip the fence before parsing instead of treating this as a retry-and-
    hope case.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```")
        stripped = stripped.strip()
    return stripped


async def enrich_game(game: Game) -> EnrichmentResult:
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_content = (
        f"Title: {game.name}\n"
        f"Summary: {game.summary or 'N/A'}\n"
        f"Genres: {', '.join(game.genres) or 'N/A'}\n"
        f"Main story length: {f'{game.hltb_main} hours' if game.hltb_main else 'N/A'}\n"
    )

    # One automatic retry on an empty/malformed response - see _call_once's
    # docstring for why this is a real observed failure mode, not paranoia.
    # `retried` is tracked on the result so reports can see how often this
    # actually happens rather than only seeing the eventual success.
    try:
        data, usage = await _call_once(client, user_content)
        retried = False
    except Exception as exc:
        logger.warning("enrich_game(%r) first attempt failed (%r), retrying once", game.name, exc)
        data, usage = await _call_once(client, user_content)
        retried = True

    # Defense in depth: the prompt constrains Claude to CUSTOM_CATEGORIES, but
    # don't let a model slip-up put an uncontrolled value into the taxonomy -
    # silently drop anything outside the list rather than storing it.
    raw_categories = data.get("custom_categories", [])
    categories = [c for c in raw_categories if c in CUSTOM_CATEGORIES]

    return EnrichmentResult(
        story_gameplay_ratio=data["story_gameplay_ratio"],
        custom_categories=categories,
        pacing_score=data["pacing_score"],
        mechanical_execution_focus=data["mechanical_execution_focus"],
        core_loop=data["core_loop"],
        tone_atmosphere=data["tone_atmosphere"],
        narrative_style=data["narrative_style"],
        player_fit=data["player_fit"],
        player_fit_mismatch=data["player_fit_mismatch"],
        standout_strengths=data.get("standout_strengths", []),
        common_complaints=data.get("common_complaints", []),
        comparable_games=data.get("comparable_games", []),
        usage=usage,
        retried=retried,
    )
