"""HowLongToBeat matching, via the unofficial `howlongtobeatpy` scraper.

No sanctioned API exists (see game-recommender-mvp-plan.md section 1/5) - this
can break if HLTB changes its site. Titles rarely match IGDB exactly (editions,
subtitles, punctuation), so results are fuzzy-matched with rapidfuzz and only
accepted above a confidence threshold; anything below is logged as unmatched
rather than silently attached to the wrong game.
"""

import logging

from howlongtobeatpy import HowLongToBeat
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 85  # rapidfuzz token_sort_ratio, 0-100


class HLTBMatch:
    def __init__(self, main: float | None, main_extra: float | None, completionist: float | None):
        self.main = main
        self.main_extra = main_extra
        self.completionist = completionist


async def match_game(igdb_title: str) -> HLTBMatch | None:
    results = await HowLongToBeat().async_search(igdb_title)
    if not results:
        logger.info("HLTB: no results for %r", igdb_title)
        return None

    best = max(results, key=lambda r: fuzz.token_sort_ratio(igdb_title, r.game_name))
    score = fuzz.token_sort_ratio(igdb_title, best.game_name)

    if score < MATCH_THRESHOLD:
        logger.info("HLTB: best match %r for %r scored %d, below threshold", best.game_name, igdb_title, score)
        return None

    return HLTBMatch(
        main=best.main_story,
        main_extra=best.main_extra,
        completionist=best.completionist,
    )
