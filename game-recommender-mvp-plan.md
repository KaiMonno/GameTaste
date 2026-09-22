# AI Game Recommender — MVP Plan

## 0. Core Idea
User specifies constraints (hard filters + soft preferences) → system pulls candidate games from IGDB/HLTB → scores & ranks them → an LLM generates a "why you'll like it / why you might not" blurb + % match per game, sorted highest to lowest.

The profile system (Steam import, wishlist, PC specs, etc.) is valuable but should come **after** the core loop works, since it's a separate, harder problem (auth, data import, ongoing sync) that doesn't need to block validating the recommendation quality.

---

## 1. Data Sources & Known Gaps

| Need | Source | Notes / Risk |
|---|---|---|
| Genre, platform, IGDB score, popularity, similar games, game modes (SP/MP/co-op) | **IGDB API** | Solid, structured, official. Rate-limited (4 req/sec) — needs local caching, not live calls per query. |
| Game length | **HowLongToBeat** | **No official API.** Community libraries (e.g. `howlongtobeatpy`) scrape HLTB's site and can break anytime. Matching IGDB titles to HLTB titles requires fuzzy string matching (titles/editions differ). Budget time for this. |
| Difficulty | Nowhere structured | **Decision: excluded entirely, not just deferred.** No structured source exists (not in IGDB or HLTB), and LLM-inferred difficulty was judged too unreliable to be worth the estimate disclaimer. Not a filter, not a scoring axis, not an enrichment field. |
| Story vs. gameplay ratio | Nowhere structured | Same problem — likely needs an LLM to infer a 0–100 score from IGDB summary + genre/theme tags + review text, cached once per game. Not real-time. |
| Content warnings | Nowhere structured | **Decision: excluded entirely, not just deferred** (same call as difficulty, same reasoning — no ground truth source, not worth the estimate-disclaimer burden). Not a filter, not a scoring axis, not an enrichment field. |
| Custom categories (Horror, Roguelike, Roguelite, Soulslike, Metroidvania, CRPG, Immersive Sim) | Nowhere in IGDB — no genre field covers these | **Added in Phase 3.5.** LLM-classified against a closed taxonomy (never freeform), cached per game like story_gameplay_ratio. Filtered exactly like an IGDB genre — `include_genres`/`exclude_genres` match against genres OR custom_categories, and the `/games/facets` endpoint unions both into one list, so the frontend and API consumers never need to know which source a tag came from. |
| Mobile exclusion | IGDB `platforms` field | Straightforward filter. |
| Backlog exclusion (owned/played) | Steam API (has official API) / Backloggd (**no public API** — scraping is ToS-gray) | Steam import is easy and official. Backloggd import is a "maybe later, unofficial" feature. |

**Takeaway:** IGDB gives you genre/platform/score/popularity/similarity/multiplayer cleanly. Length and story-vs-gameplay require either scraping (fragile) or LLM-inference-and-cache (more reliable, costs tokens once per game, not per query). Plan for a **pre-processing pipeline** that enriches a game once and stores it, rather than computing this live per user request. Difficulty and content warnings were both considered here but are excluded from scope entirely, not just this pipeline.

---

## 2. Architecture (MVP)

```
[IGDB API] ---nightly sync---> [Postgres: games table] <---enrichment job--- [Claude API]
[HLTB match]---nightly sync--/        |                (story/gameplay — cached once)
                                       v
                              [Recommendation Engine]
                              (hard filters -> candidate set
                               -> weighted soft-match scoring)
                                       |
                                       v
                              [Claude API: per-candidate
                               "why/why not" blurb + confidence]
                                       |
                                       v
                                  [Frontend: ranked list
                                   with % match]
```

- **Backend:** Python (FastAPI) — good ecosystem for IGDB/HLTB scraping libs and easy Claude API integration.
- **DB:** Postgres. One `games` table as the unified, enriched record (IGDB fields + HLTB length + LLM-derived tags), refreshed on a schedule, not per request.
- **Frontend:** Simple web form matching your filter list → results page.
- **LLM use has two distinct jobs, don't conflate them:**
  1. **Offline enrichment** (batch, cached): infer story/gameplay ratio once per game.
  2. **Online explanation** (per query, on the ~20 shortlisted candidates only): generate the "why/why not" blurb and reconcile it into a % match — cheap because it's only run on a short pre-filtered list, not the whole catalog.

---

## 3. Recommendation Logic

**Step 1 — Hard filters (reduce catalog to candidates):**
Genre include/exclude, platform, "no mobile" (always on, not user-facing), "no DLC/expansions" (always on, not user-facing), multiplayer requirement if mandatory. These are binary — a game either passes or it's out.

**Step 2 — Soft scoring (rank remaining candidates):**
Weighted distance from user's target on continuous/ordinal axes:
- Game length (distance from target hours)
- Review score (threshold or gradient above a minimum)
- Popularity/nichety (distance from target — e.g. IGDB `rating_count`/Steam review count as a proxy)
- Story vs. gameplay (distance from target ratio)
- Similarity to a reference game (use IGDB's `similar_games` field as a first pass; a proper embedding-similarity model is a v2 upgrade)

Combine into a single weighted score → normalize to a 0–100% match.

**Step 3 — LLM pass on top N (e.g. top 15–20):**
Feed each candidate's stats + the user's stated preferences to Claude, ask for a short "why recommended" and "why you might not like it," in the same response as the numeric % (or reconcile the LLM's qualitative sense with the computed score — decide upfront whether the % is purely the formula, purely the LLM, or a blend; a purely formula-driven % is more consistent and auditable for MVP).

---

## 4. Phased Build Plan

**Phase 1 — Data foundation**
- IGDB sync job (subset: popular + all platforms you care about, expand later)
- HLTB matching pipeline + fuzzy title matcher
- Store unified `games` table

**Phase 2 — Enrichment pipeline**
- LLM batch job: story/gameplay ratio per game (cached, re-run only when stale) — **done**, all 415 recommendable games enriched (see below)
- Manual spot-check a sample for accuracy before trusting it at scale — **done**, spot-checked twice (8-game and 6-game batches), output was specific and accurate both times

**Phase 3 — Core recommendation engine (no accounts, no profile)**
- Filter form → hard filter → soft-score → return ranked list, no LLM blurbs yet (just numeric % match) — **done**
- This validates whether the scoring logic *feels* right before spending LLM budget on explanations —
  **validated**: tested each soft-scoring axis independently and combined (story/gameplay ratio, popularity,
  length, genre+platform hard filters together) against the real 415-game catalog; results tracked distance
  from target sensibly. `similar_to_game_id` is wired on the backend but has no frontend UI yet (needs a
  game-search/picker, not just a number field) - left for a later pass.
  - **Popularity scoring turned out to be broken** on closer testing after Phase 3 shipped - see Phase 3.5.

**Phase 3.5 — Cleanup: custom categories + popularity fix** (before Phase 4, not a numbered plan phase)
- **Custom categories added**: IGDB has no genre for Horror, Roguelike, Roguelite, Soulslike, Metroidvania,
  CRPG, or Immersive Sim - added a `custom_categories` column, classified via the same offline/cached LLM
  enrichment job (not a new pipeline), against a closed taxonomy so Claude can't invent ungoverned tags.
  Filtered exactly like a genre (see table above) - the frontend needed zero changes.
- **Popularity scoring fixed** - it was structurally broken, not just mistuned: (1) the linear
  `distance/5000` formula was far too coarse for the catalog's actual right-skewed rating_count distribution
  (p90 is ~1800, max is ~5950), so almost every game scored 0.85-1.0 regardless of target; (2) `review_score`
  was unconditionally included in every query's scoring at equal-or-higher weight than the axis the user
  actually asked for, so it silently overrode explicit niche requests. Fixed with a log-normalized 0-100
  popularity score computed relative to the actual candidate set (not a global constant - "niche" means
  niche within, say, the RPG subset if genre-filtered) and rebalanced weights (review_score 1.0 → 0.4,
  popularity 0.5 → 1.0) so quality acts as a tiebreaker instead of a dominant axis. `target_popularity` is
  now 0 (niche) - 100 (popular), not a raw rating_count.
  - **Superseded by Phase 3.6 below** - IGDB popularity as a *user-facing preference* (this whole
    `target_popularity` mechanism) was removed entirely, not just re-fixed again. The log-normalization
    machinery this fix built was correct and got reused, just repurposed for something different.

**Phase 3.6 — Remove IGDB popularity as a preference; add discovery bias; Backloggd Top 100 benchmark**

Product decision: IGDB `rating_count`-based "popularity" is not a good proxy for what this project actually
wants, which is *discovery* for enthusiast players - a game being extremely popular shouldn't inherently make
it a better recommendation, and the reverse (deliberately down-ranking popular games) isn't the goal either.

- **`target_popularity` removed entirely** - no more slider, no more soft preference, no more "popularity"
  scoring axis in `WEIGHTS`. Not replaced with another popularity-flavored axis.
- **Discovery bias added instead** - a small, always-on nudge (not a user preference) that can tip a close
  call toward the less-obvious game but is capped (`DISCOVERY_BIAS_WEIGHT = 6.0` match_score points) so it
  can never overturn a genuinely better match (a 25-point preference-match gap, e.g. 95 vs 70, can never be
  closed by discovery alone). See `services/scoring.py`'s module docstring for the full reasoning, including
  why `igdb_rating_count` (log-normalized relative to the candidate set - the same machinery from the Phase
  3.5 fix, repurposed) was chosen over the other signals considered (IGDB's real Popularity Primitives API
  was never integrated by this project; release date isn't synced at all; a curated "mainstream set" is
  exactly what the Backloggd Top 100 benchmark below must *not* be used for).
- **Backloggd Top 100 benchmark/reference table added** (`backloggd_top_100`, see `models.py`) - a small,
  recognizable set of highly-regarded games for evaluating recommendation quality by hand, explicitly NOT a
  scoring input and NOT the primary catalog. `scripts/match_backloggd_top100.py` fuzzy-matches titles to
  `games` rows and flags ambiguous matches rather than guessing.
  - **Known limitation**: this script does not scrape Backloggd itself. `backloggd.com/games/top-100/` is
    protected by a JS bot-challenge (Bunny Shield) that blocks plain HTTP fetches (confirmed: 403 from both
    `curl` and this project's web-fetch tooling; no Wayback Machine snapshot exists either). The matching
    pipeline is fully built and tested against synthetic data - it just needs the actual 100 titles supplied
    via a JSON file (see `scripts/data/README.md`) until real automated fetching is solved, which would need
    a real headless browser (a meaningfully heavier dependency, out of scope for this task).
- **Test suite added** (`backend/tests/`, previously nonexistent) - `pytest` + `pytest-asyncio`, unit tests
  for the scoring/discovery-bias math and the Backloggd matching algorithm, integration tests against the
  real dev catalog. See test docstrings for what each demonstrates, not just "does it run".

**Phase 4 — Explanations**
- Add the per-candidate LLM "why/why not" call on the top N results

**Phase 5 — Basic profile**
- Accounts, saved preference defaults, wishlist (simple save-a-game-to-list)

**Phase 6 — Steam import**
- OAuth or API-key based Steam library pull → auto-exclude owned/played games from recommendations

**Phase 7 — Extended profile**
- PC specs (compare against IGDB/Steam min-spec data if available), consoles owned, emulator support, controller availability — these affect *filtering* (can this person even run/play this game) more than *matching*, so they slot in as additional hard filters once the core engine exists

**Phase 8 (stretch) — Backloggd import**
- Only if a reliable, ToS-acceptable path exists; otherwise leave as manual CSV import from the user

---

## 5. Open Risks to Resolve Before Building

1. **HLTB has no sanctioned API** — confirm you're comfortable with a scraping dependency, or scope MVP to games where length data is missing gracefully (show "unknown" rather than blocking).
2. **Story-vs-gameplay has no ground truth** — decide how much you disclose "this is AI-estimated" vs. trying to source community data instead. (Difficulty and content warnings had the same problem and were both resolved by cutting them entirely rather than disclosing an estimate.)
3. **% match methodology** — decide early whether it's a transparent formula (more trustworthy, explainable) or LLM-judged (more nuanced, less consistent). Mixing both without a clear reconciliation rule will feel arbitrary to users.
4. **IGDB rate limits** — you cannot hit IGDB live per user query at scale; the nightly-sync-and-cache model is mandatory, not optional.

---

## 6. Suggested MVP Cut (What to actually build first)

The smallest version that proves the concept: **Phases 1–4**, single form, no accounts, no imports. IGDB + HLTB data on a static/nightly-synced catalog, hard filters, weighted scoring, LLM explanations on the top 15. That alone tests whether the recommendation quality is good enough to justify building the profile system around it.
