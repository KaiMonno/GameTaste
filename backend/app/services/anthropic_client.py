"""Shared, hardened Claude API calling logic - retry-once on an empty/
malformed response, scanning all content blocks for the actual text block,
and stripping markdown code fences Claude sometimes adds despite being told
not to.

Originally built in llm_enrichment.py (offline enrichment) and extracted
here once llm_explanations.py (Phase 4's live, per-query calls) needed the
identical hardening - three real bugs were found running enrichment against
hundreds of games, each would recur in any other caller of this model that
didn't know to guard against them:

1. max_tokens too tight: Sonnet 5 does internal extended thinking on these
   prompts, and thinking tokens count against max_tokens - a response can
   truncate (stop_reason="max_tokens") before producing any visible JSON if
   the budget is too small. Give callers enough headroom.
2. response.content[0] isn't always the text block - when extended thinking
   is used, content[0] is a *thinking* block (no `.text`) and the real
   answer is content[1]. Indexing [0] misreads this as an empty response
   even though valid JSON is sitting right there (stop_reason="end_turn",
   real thinking_tokens consumed). This alone caused a ~9% failure/wasted-
   retry rate before being found.
3. Claude occasionally wraps the answer in a ```json ... ``` fence despite
   the system prompt saying not to (reproducibly observed for at least one
   real game). json.loads on a string starting with a backtick fails with
   "Expecting value: line 1 column 1 (char 0)" - indistinguishable from a
   genuinely empty response unless you strip the fence first.
"""

import json
import logging

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Generous headroom for extended thinking - see bug #1 above. Individual
# callers may need more for a larger expected output (e.g. a batched call
# over several games), not less.
DEFAULT_MAX_TOKENS = 2000

# Offline enrichment (llm_enrichment.py) deliberately stays on Sonnet 5 - it's
# a background job, latency doesn't matter, and the per-game analysis it does
# from scratch (inferring pacing/tone/complaints/etc. from just a summary)
# benefits from the stronger model. Haiku is for the live, user-facing path
# (llm_explanations.py) where speed is the point and the task is simpler -
# reconciling analysis Sonnet already did, not generating it.
MODEL_SONNET = "claude-sonnet-5"
MODEL_HAIKU = "claude-haiku-4-5-20251001"


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```")
        stripped = stripped.strip()
    return stripped


async def _call_once(
    client: AsyncAnthropic, model: str, system_prompt: str, user_content: str, max_tokens: int
) -> tuple[dict | list, dict]:
    """One API call + parse attempt. Returns (parsed_json, usage_dict). Raises
    with diagnostic detail (stop_reason, content block types) rather than a
    bare JSONDecodeError/TypeError if the response has no usable text
    content, so any recurrence is debuggable instead of exploding blindly.
    """
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
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


async def call_claude_json(
    client: AsyncAnthropic,
    system_prompt: str,
    user_content: str,
    model: str = MODEL_SONNET,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    log_context: str = "",
) -> tuple[dict | list, dict, bool]:
    """Calls Claude expecting a JSON (object or array) response, with one
    automatic retry on an empty/malformed response. Returns
    (parsed_json, usage_dict, retried). `log_context` is just for the
    warning log line (e.g. a game name or batch description) - purely
    cosmetic, doesn't affect behavior.
    """
    try:
        data, usage = await _call_once(client, model, system_prompt, user_content, max_tokens)
        return data, usage, False
    except Exception as exc:  # noqa: BLE001 - logged, then retried once
        logger.warning("call_claude_json(%s) first attempt failed (%r), retrying once", log_context, exc)
        data, usage = await _call_once(client, model, system_prompt, user_content, max_tokens)
        return data, usage, True
