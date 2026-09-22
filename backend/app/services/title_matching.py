"""Shared fuzzy title-matching logic against a candidate pool of `Game` rows.

Extracted from scripts/match_backloggd_top100.py (pure refactor, no behavior
change) so the same matching rules apply everywhere a title needs resolving
to a `games` row - the Backloggd Top 100 matcher and the titles-file
resolution in scripts/enrich_games.py both import this rather than keeping
two copies of the same logic to drift apart.
"""

from rapidfuzz import fuzz

from app.models import Game

# A title is only accepted as a confident match if its best candidate scores
# at least this well...
MIN_MATCH_SCORE = 80
# ...AND beats the next-best candidate by at least this much. Below this
# margin the two candidates are too close to tell apart automatically (e.g.
# a base game vs. its own remaster both scoring ~90) - flagged "ambiguous"
# rather than silently picking one.
MIN_AMBIGUITY_MARGIN = 5

_ROMAN_NUMERALS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
}


def _is_number_token(token: str) -> bool:
    normalized = token.strip(":,-").upper()
    return normalized.isdigit() or normalized in _ROMAN_NUMERALS


def _differs_only_by_trailing_sequel_number(name_a: str, name_b: str) -> bool:
    """True when `name_a` and `name_b` are identical except one has exactly
    one extra trailing token, and that extra token is a bare number/roman
    numeral - e.g. "Slay the Spire" vs "Slay the Spire 2". False for
    "Final Fantasy VII" vs "Final Fantasy VII Remake": the bodies aren't
    equal once you drop the last token of the longer one (VII stays in
    both; only "Remake" is extra), so that's a qualifier/edition suffix,
    not a different installment, and must NOT be blocked here.
    """
    tokens_a, tokens_b = name_a.strip().split(), name_b.strip().split()
    if len(tokens_a) == len(tokens_b) + 1:
        longer, shorter = tokens_a, tokens_b
    elif len(tokens_b) == len(tokens_a) + 1:
        longer, shorter = tokens_b, tokens_a
    else:
        return False

    if [t.casefold() for t in longer[:-1]] != [t.casefold() for t in shorter]:
        return False

    return _is_number_token(longer[-1])


def find_best_matches(title: str, candidates: list[Game]) -> list[tuple[Game, float]]:
    """All candidates scored against `title` via rapidfuzz token_sort_ratio
    (same approach as services/hltb_client.py's title matching), best first.
    """
    scored = [(game, fuzz.token_sort_ratio(title, game.name)) for game in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def classify_match(title: str, candidates: list[Game]) -> tuple[Game | None, str, float | None]:
    """Returns (matched_game_or_None, status, confidence). status is one of
    "matched", "ambiguous", "unmatched".

    A literal exact-string match (case-insensitive) short-circuits the
    fuzzy-margin ambiguity check below - discovered to matter in practice:
    "Final Fantasy VII" vs "Final Fantasy VIII" scores ~97 via
    token_sort_ratio purely because the strings share nearly every token,
    even though they're unambiguously different games. An exact string
    match is the strongest signal this matcher can get, stronger than "how
    much closer is the fuzzy runner-up" - so it's trusted outright, UNLESS
    more than one candidate exactly matches the title (a true name
    collision, e.g. two different IGDB rows both literally named "Shadow of
    the Colossus" for the PS2 original and PS4 remake) - that case still
    must be flagged.
    """
    normalized_title = title.strip().casefold()
    exact_matches = [g for g in candidates if g.name.strip().casefold() == normalized_title]
    if len(exact_matches) == 1:
        return exact_matches[0], "matched", 100.0
    if len(exact_matches) > 1:
        return None, "ambiguous", 100.0

    scored = find_best_matches(title, candidates)
    if not scored:
        return None, "unmatched", None

    best_game, best_score = scored[0]
    if best_score < MIN_MATCH_SCORE:
        return None, "unmatched", best_score

    if len(scored) > 1:
        _, second_score = scored[1]
        if best_score - second_score < MIN_AMBIGUITY_MARGIN:
            return None, "ambiguous", best_score

    # A high fuzzy score alone can't distinguish "same game, different
    # numeral notation" (Baldur's Gate 3 vs III - should match) from "a
    # different installment with an almost-identical name" (Slay the Spire
    # vs Slay the Spire 2 - must NOT match). token_sort_ratio scores the
    # latter pair ~93, comfortably past MIN_MATCH_SCORE, with nothing else
    # in the candidate pool close enough to trip the ambiguity check above -
    # a real bug found running this: a request for "Slay the Spire 2"
    # silently resolved to the existing "Slay the Spire" row, since only
    # one of the two existed in the pool to compare against. Guard: refuse
    # a match that's otherwise identical except for exactly one bare
    # trailing number/numeral token, falling through as "unmatched" instead
    # - the caller can then try elsewhere (e.g. an IGDB search, which does
    # return sequels as distinct entries).
    if _differs_only_by_trailing_sequel_number(title, best_game.name):
        return None, "unmatched", best_score

    return best_game, "matched", best_score
