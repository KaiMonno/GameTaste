"""Tests for the Backloggd Top 100 title-matching algorithm
(scripts/match_backloggd_top100.py classify_match/find_best_matches).

IMPORTANT: these use synthetic, made-up candidate pools - NOT a real fetch
of Backloggd's actual Top 100 (which this project cannot currently fetch
automatically, see that script's module docstring). This tests that the
*matching logic* behaves correctly (exact match, near-fuzzy match, ambiguous
multi-candidate case flagged rather than guessed, no-match case) - it does
not and cannot test against real Backloggd data until that data is available.
"""

from app.scripts.match_backloggd_top100 import MIN_MATCH_SCORE, classify_match
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
