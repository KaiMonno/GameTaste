"""Tests for the shared fuzzy title-matching logic (services/title_matching.py)
- used by both scripts/match_backloggd_top100.py and the --titles-file
resolution flow in scripts/enrich_games.py.

IMPORTANT: these use synthetic, made-up candidate pools, not real fetched
data from either Backloggd or IGDB. This tests that the *matching logic*
behaves correctly (exact match, near-fuzzy match, ambiguous multi-candidate
case flagged rather than guessed, no-match case).
"""

from app.services.title_matching import MIN_MATCH_SCORE, classify_match
from tests.conftest import make_game


def test_exact_title_match():
    candidates = [make_game(id=1, name="Elden Ring"), make_game(id=2, name="Dark Souls III")]
    game, status, confidence = classify_match("Elden Ring", candidates)
    assert status == "matched"
    assert game.id == 1
    assert confidence == 100.0


def test_close_fuzzy_match_with_edition_suffix():
    """Backloggd/IGDB titles often differ by a short edition/remake suffix -
    a close but not-exact match should still resolve confidently when
    there's no similarly-scoring competitor. (Verified against real
    rapidfuzz output: "Final Fantasy VII" vs "Final Fantasy VII Remake"
    scores ~83, comfortably past MIN_MATCH_SCORE=80 - a *long* suffix like
    "- Game of the Year Edition" scores much lower and correctly falls to
    "unmatched" instead, which is intentional: see
    test_long_suffix_difference_is_unmatched_not_a_bad_guess below.)
    """
    candidates = [
        make_game(id=1, name="Final Fantasy VII Remake"),
        make_game(id=2, name="Stardew Valley"),
    ]
    game, status, confidence = classify_match("Final Fantasy VII", candidates)
    assert status == "matched"
    assert game.id == 1
    assert confidence > 80


def test_long_suffix_difference_is_unmatched_not_a_bad_guess():
    """The flip side of the above: when a title differs enough (a long
    edition suffix) that confidence drops below MIN_MATCH_SCORE, the right
    behavior is "unmatched", not a low-confidence guess.
    """
    candidates = [make_game(id=1, name="The Witcher 3: Wild Hunt - Game of the Year Edition")]
    game, status, confidence = classify_match("The Witcher 3: Wild Hunt", candidates)
    assert status == "unmatched"
    assert game is None
    assert confidence is not None and confidence < MIN_MATCH_SCORE


def test_sequel_is_not_matched_to_its_predecessor():
    """Real bug found while running a titles-file enrichment: "Slay the
    Spire 2" fuzzy-matched to the existing "Slay the Spire" row at ~93
    score, with nothing else in the pool close enough to trip the
    ambiguity-margin check (only one of the two titles existed to compare
    against). A sequel must never be silently matched to its predecessor
    just because no better candidate exists yet.
    """
    candidates = [make_game(id=1, name="Slay the Spire")]
    game, status, confidence = classify_match("Slay the Spire 2", candidates)
    assert status == "unmatched"
    assert game is None


def test_numeral_notation_difference_still_matches():
    """The other side of the fix above: "Baldur's Gate 3" vs "Baldur's Gate
    III" is the SAME game in different numeral notation (3 == III) and must
    still match confidently - the sequel-number guard should only block a
    match when the trailing numbers genuinely differ, not whenever a number
    is present at all.
    """
    candidates = [make_game(id=1, name="Baldur's Gate III"), make_game(id=2, name="Stardew Valley")]
    game, status, confidence = classify_match("Baldur's Gate 3", candidates)
    assert status == "matched"
    assert game.id == 1


def test_ambiguous_match_is_flagged_not_guessed():
    """Two different candidates score close enough to each other that
    picking one over the other would be a guess - must be flagged
    "ambiguous" rather than silently picking one, per the task's explicit
    "flag ambiguous cases rather than silently matching the wrong game".
    (Verified against real rapidfuzz output: "Dark Souls" vs "Dark Souls II"
    scores ~87, vs "Dark Souls III" scores ~83 - a ~4-point gap, under
    MIN_AMBIGUITY_MARGIN=5.)
    """
    candidates = [
        make_game(id=1, name="Dark Souls II"),
        make_game(id=2, name="Dark Souls III"),
    ]
    game, status, confidence = classify_match("Dark Souls", candidates)
    assert status == "ambiguous"
    assert game is None, "an ambiguous match must not silently return a guessed game"


def test_exact_match_beats_a_coincidentally_close_franchise_sibling():
    """Real bug found matching the actual Backloggd Top 100: "Final Fantasy
    VII" vs "Final Fantasy VIII" scores ~97 via token_sort_ratio (they share
    nearly every token), which used to trip the ambiguity-margin check even
    though there's exactly one literal exact-name match and the "runner-up"
    is a completely different, unambiguous game. An exact string match must
    win outright, not get flagged ambiguous by an unrelated sequel's
    coincidentally close fuzzy score.
    """
    candidates = [
        make_game(id=1, name="Final Fantasy VII"),
        make_game(id=2, name="Final Fantasy VIII"),
    ]
    game, status, confidence = classify_match("Final Fantasy VII", candidates)
    assert status == "matched"
    assert game.id == 1


def test_true_name_duplicate_is_still_ambiguous():
    """The other side of the fix above: when *multiple* candidates are
    literal exact-string matches (a real IGDB duplicate, e.g. an original
    and its same-named remake both stored as "Shadow of the Colossus"), the
    exact-match short-circuit must not just pick the first one - still
    ambiguous.
    """
    candidates = [
        make_game(id=1, name="Shadow of the Colossus"),
        make_game(id=2, name="Shadow of the Colossus"),
    ]
    game, status, confidence = classify_match("Shadow of the Colossus", candidates)
    assert status == "ambiguous"
    assert game is None


def test_unrelated_title_is_unmatched():
    candidates = [make_game(id=1, name="Elden Ring"), make_game(id=2, name="Stardew Valley")]
    game, status, confidence = classify_match("Some Completely Different Game Title", candidates)
    assert status == "unmatched"
    assert game is None


def test_empty_candidate_pool_is_unmatched_not_a_crash():
    game, status, confidence = classify_match("Elden Ring", [])
    assert status == "unmatched"
    assert game is None
    assert confidence is None
