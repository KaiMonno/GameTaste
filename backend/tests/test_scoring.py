"""Tests for the Phase 3.6 change: IGDB popularity removed as a preference,
replaced by a small always-on discovery bias. See
game-recommender-mvp-plan.md Phase 3.6 and services/scoring.py's module
docstring for the full reasoning - these tests exist to *demonstrate* that
reasoning holds against real numbers, not just that the code runs.
"""

from app.schemas import SoftPreferences
from app.services.scoring import (
    DISCOVERY_BIAS_WEIGHT,
    WEIGHTS,
    _discovery_log_bounds,
    rank_candidates,
    score_candidate,
)
from tests.conftest import make_game


# --- B. No popularity preference -------------------------------------------


def test_no_popularity_field_on_soft_preferences():
    """target_popularity must not exist on the API surface at all anymore -
    not just "unused", genuinely removed."""
    assert "target_popularity" not in SoftPreferences.model_fields


def test_no_popularity_axis_in_weights():
    """The old scoring axis is gone, not just given a zero weight - a zero
    weight would still leave dead code/API surface around it."""
    assert "popularity" not in WEIGHTS


def test_rating_count_alone_no_longer_drives_ranking_like_a_preference():
    """Before this change, a game with a higher rating_count could win purely
    because target_popularity was set high - popularity had a full axis
    weight (1.0) it could dominate with. Now there is no such target: varying
    rating_count by itself can only move a score by up to DISCOVERY_BIAS_WEIGHT
    points (the discovery bias cap), never more.
    """
    preferences = SoftPreferences(target_length_hours=10)
    mainstream = make_game(id=1, igdb_rating=80, hltb_main=10, igdb_rating_count=100_000)
    niche = make_game(id=2, igdb_rating=80, hltb_main=10, igdb_rating_count=50)
    bounds = _discovery_log_bounds([mainstream, niche])

    mainstream_score = score_candidate(mainstream, preferences, bounds)
    niche_score = score_candidate(niche, preferences, bounds)

    # Same preference match on every other axis - the only real difference is
    # rating_count, so the entire gap between them must be <= the discovery
    # cap, not an unbounded swing.
    assert abs(niche_score - mainstream_score) <= DISCOVERY_BIAS_WEIGHT + 0.01


# --- A. Niche vs mainstream --------------------------------------------------


def test_niche_gets_modest_boost_when_matches_are_equally_good():
    """Two games that match the user's stated preferences identically well -
    the more niche one should rank higher, but only by a modest amount."""
    preferences = SoftPreferences(target_length_hours=10, target_story_gameplay_ratio=50)

    mainstream = make_game(
        id=1, name="Mainstream Game", igdb_rating=85, hltb_main=10, story_gameplay_ratio=50,
        igdb_rating_count=6000,
    )
    niche = make_game(
        id=2, name="Niche Game", igdb_rating=85, hltb_main=10, story_gameplay_ratio=50,
        igdb_rating_count=400,
    )

    ranked = rank_candidates([mainstream, niche], preferences, limit=10)
    ranked_names = [game.name for game, _ in ranked]
    scores = {game.name: score for game, score in ranked}

    assert ranked_names[0] == "Niche Game", "the equally-good-match niche game should rank first"
    gap = scores["Niche Game"] - scores["Mainstream Game"]
    assert 0 < gap <= DISCOVERY_BIAS_WEIGHT + 0.01, (
        f"discovery boost should be positive but capped at ~{DISCOVERY_BIAS_WEIGHT} points, got {gap}"
    )


def test_significantly_better_match_wins_even_if_mainstream():
    """The worked example from the spec: a 95%-ish match that's mainstream
    must still beat a 70%-ish match that's niche. Discovery is a tiebreaker,
    not a way to force obscure games to the top regardless of fit.
    """
    preferences = SoftPreferences(target_length_hours=10)

    excellent_mainstream = make_game(
        id=1, name="Excellent Mainstream Match", igdb_rating=90, hltb_main=10, igdb_rating_count=6000
    )
    # hltb_main far from the target=10 request -> poor length match.
    poor_niche = make_game(
        id=2, name="Poor Niche Match", igdb_rating=90, hltb_main=40, igdb_rating_count=400
    )

    ranked = rank_candidates([excellent_mainstream, poor_niche], preferences, limit=10)
    assert ranked[0][0].name == "Excellent Mainstream Match", (
        "a much worse match must not win just for being niche - "
        f"got order {[g.name for g, _ in ranked]}"
    )


def test_discovery_bias_applies_even_with_no_soft_preferences_set():
    """The bias is a general system behavior, not tied to any specific
    preference being requested - it should still nudge rankings on a pure
    hard-filter browse (no soft preferences at all).
    """
    preferences = SoftPreferences()  # nothing set

    mainstream = make_game(id=1, name="Mainstream", igdb_rating=80, igdb_rating_count=6000)
    niche = make_game(id=2, name="Niche", igdb_rating=80, igdb_rating_count=400)

    ranked = rank_candidates([mainstream, niche], preferences, limit=10)
    assert ranked[0][0].name == "Niche"


def test_missing_rating_count_gets_no_discovery_boost():
    """A game with unknown rating_count must not be treated as automatically
    maximally niche - that would manufacture an unearned advantage from
    missing data, which contradicts the rest of the codebase's convention
    (missing enrichment -> neutral, never an automatic win or loss).
    """
    preferences = SoftPreferences(target_length_hours=10)
    known = make_game(id=1, igdb_rating=80, hltb_main=10, igdb_rating_count=400)
    unknown = make_game(id=2, igdb_rating=80, hltb_main=10, igdb_rating_count=None)

    bounds = _discovery_log_bounds([known, unknown])
    known_score = score_candidate(known, preferences, bounds)
    unknown_score = score_candidate(unknown, preferences, bounds)

    # unknown gets its raw match_score with +0 boost; known gets its raw
    # match_score plus some positive boost (400 is the niche end of a 2-game
    # set) - so known should score >= unknown, not the reverse.
    assert known_score >= unknown_score
