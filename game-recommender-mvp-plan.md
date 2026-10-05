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

**Phase 3.7 — Curated recommendation set**

Product decision: recommendations should come ONLY from a hand-picked list of niche/obscure games (the
repo-root `Game List` file), not the broad IGDB-synced catalog - the broad catalog's enriched mainstream
games are kept around (so their IGDB/HLTB/LLM-enrichment work isn't wasted if re-curated later) but are
never recommendation candidates.

- **`curated_list_games` table added** (`models.CuratedListGame`) - a membership table, not a boolean flag
  on `games`, so removal is a clean delete rather than hunting down a scattered column (mirrors the
  `backloggd_top_100` table's shape, though that one stays explicitly NOT a scoring input - this one is).
- **`scripts/sync_curated_list.py` added** - treats `Game List` as the single source of truth and diffs
  current membership against it (adds newly-listed titles via the same IGDB-search + HLTB-match resolution
  `enrich_games.py --titles-file` already used, removes titles no longer listed) rather than taking manual
  add/remove commands. Workflow going forward: edit `Game List`, run this script, then run
  `enrich_games.py` (no args) to enrich anything newly added.
- **`services/scoring.py` `restrict_to_curated_list()` added** - deliberately NOT folded into
  `apply_hard_filters`, which is also reused by `match_backloggd_top100.py` and `enrich_games.py
  --titles-file` to check filter-exclusion correctness against the FULL catalog, independent of curation.
  Wired into `/recommendations` and the default (no-args) `enrich_games.py` query, so a plain enrichment
  run now only ever spends LLM budget on curated games. `/games/facets` is scoped the same way, so the
  filter UI never offers a genre/platform that returns zero curated results.

**Phase 4 — Explanations** — **done**
- Add the per-candidate LLM "why/why not" call on the top N results — **wired into `/recommendations`**:
  called on the final 5 diverse results only (never the broader 20-candidate shortlist), batched into
  one call. Grounded in the v3 enrichment fields already computed offline per game (core_loop,
  tone_atmosphere, player_fit, standout_strengths, common_complaints, ...) rather than asking Claude to
  analyze each game from scratch live - keeps the live call cheap (~$0.0125/search, ~7s, measured against
  real data) since the hard analytical work already happened once per game, offline; this call's only job
  is reconciling that existing analysis with what *this specific query* asked for. Verified live: asking
  for ~10hr/70%-story games produced explanations that correctly cited the actual length/ratio match (or
  honestly flagged a real mismatch, e.g. "runs about 13 hours, longer than your target") rather than
  generic text.
  - Reused `services/anthropic_client.py` (extracted from `llm_enrichment.py`) for the same hardened
    call logic (retry-once, correct content-block scanning, markdown-fence stripping) rather than
    re-forking a naive implementation that would hit the identical three bugs again.
  - Explanations are best-effort: if the live call fails for any reason, `/recommendations` still returns
    its 5 numeric results with `why_recommended`/`why_not` left null, rather than failing the whole
    search - the formula-driven match score must never depend on a live LLM call succeeding. Tested via
    monkeypatched failure, not just assumed.
  - No frontend changes needed - `ResultsList.tsx` already rendered these fields, just never had data.

**Phase 5 — Basic profile (done)**
- Accounts via Clerk (hosted auth - sign-in/sign-up UI, sessions; see
  `frontend/middleware.ts`, `frontend/app/layout.tsx`). The backend never
  sees passwords, only verifies the session token Clerk's frontend SDK
  attaches, via Clerk's own official Python SDK (`clerk-backend-api`) - see
  `backend/app/services/auth.py`. A lightweight `users` table mirrors just
  enough of the Clerk identity (the opaque `clerk_user_id`) to hang our own
  FKs off of, created lazily on first authenticated request rather than via
  a webhook sync.
  - Saved preference defaults: `user_preferences` table, one JSONB row per
    user mirroring the `HardFilters`/`SoftPreferences` schemas directly
    (`GET`/`PUT /profile/preferences`). The filter form pre-fills from this
    on sign-in and offers a "Save as my default filters" button - purely a
    convenience default for the next search, not a scoring input.
  - Wishlist: `wishlist_items` table, unique per `(user_id, game_id)` so
    saving twice is a no-op rather than a duplicate row (`GET`/`POST`/
    `DELETE /wishlist/{game_id}`). A "Save to wishlist" action appears on
    each recommendation result when signed in; `/wishlist` is a new page
    listing saved games with a remove action.
  - All three endpoints are best-effort gated: signed-out users can still
    browse and get recommendations exactly as before (Phase 5 added
    nothing gating the core loop) - only the profile/wishlist actions
    themselves require a session, enforced server-side (401), not by a
    frontend route redirect.

**Phase 6 — Steam import (done)**
- Two ways in, one backend endpoint: a pasted profile URL/vanity name/SteamID64
  (`POST /profile/steam-import`, see `backend/app/services/steam_client.py`), or "Sign in through
  Steam" (OpenID 2.0 - `frontend/app/api/steam-openid/{start,callback}/route.ts`). OpenID still
  needs the same server-held Steam Web API key for the actual `GetOwnedGames` call afterward (it
  only replaces the paste), so the manual path shipped first as the simpler MVP cut, and OpenID
  was added alongside it rather than instead of it - both call the same backend endpoint, since
  OpenID's callback resolves to a verified SteamID64 that `resolve_steam_id64` already accepts as
  a bare id with no extra backend change needed. Steam's OpenID needs no pre-registration (realm/
  return_to are supplied live, not pre-registered like an OAuth app) - the callback locally
  validates every security-relevant field (`ns`, `mode`, `op_endpoint` pinned to Steam's real
  endpoint rather than whatever the response echoes, `return_to` exact match, Steam's fixed dummy
  `assoc_handle`, `claimed_id`/`identity` well-formed and matching) *before* the actual proof: a
  server-to-server `check_authentication` call back to Steam, trusting only `is_valid: true` from
  that response - verified against a known-working reference implementation
  (danielburger1337/steam-openid-php), not reconstructed from memory, since getting this wrong
  means trusting an unverified identity claim.
  - Owned Steam appids are matched to our own `games.id` via IGDB's `external_games` endpoint
    (`external_game_source = 1` is Steam, confirmed by live query against IGDB's
    `external_game_sources` lookup table) - an id-to-id join, not fuzzy title matching. Backfilled
    for the existing catalog via `scripts/backfill_igdb_fields.py`; 452/677 synced games (161/219
    curated) have a Steam listing IGDB knows about - the rest are console exclusives or just not
    on Steam.
  - Re-importing replaces the user's library entirely (delete-then-reinsert) rather than merging,
    so a refunded/removed game stops being excluded - see `models.UserLibraryItem`.
  - `/recommendations` now takes an *optional* signed-in user (`services/auth.py
    get_current_user_optional` - None instead of a 401 on a missing/invalid token) so anonymous
    search is completely unaffected; a signed-in user's owned games are excluded from candidates
    before scoring (`services/scoring.py exclude_owned_games`).
  - "Already played" button (minimal manual counterpart to the Steam import, for a game Steam
    doesn't know about or a user who skipped linking Steam) - `POST`/`DELETE
    /profile/played/{game_id}`, writing/removing a `UserLibraryItem` row with `source="manual"`
    instead of `"steam"`. Exclusion doesn't care which source a row came from (same unique
    `(user_id, game_id)` constraint, same `exclude_owned_games` query), so this needed no new
    exclusion logic, only the two endpoints and a button on each result (`components/
    ResultsList.tsx`).

**Phase 7 — Extended profile (scoped down to what has real data; partially done)**
- Originally scoped as four sub-features: PC specs, consoles owned, emulator support, controller
  availability. Checked IGDB's actual schema live before building anything (`platforms`,
  `platform_versions`, `multiplayer_modes`) - confirmed none of PC min/recommended specs,
  controller support, or emulator compatibility exist anywhere in IGDB as structured data. PC
  specs technically exist somewhere (Steam store pages), but only via new, fragile scraping -
  same "don't estimate what has no ground truth" call as difficulty/content warnings in Phase 1.
  Deferred all three rather than build on a guess.
  - **Platforms/consoles owned - done.** The one sub-feature backed by data already synced
    (`games.platforms`, from IGDB). A persistent, always-on exclusion - not a per-search filter
    like `HardFilters.platforms` (which this is additive to, not a replacement for) - the same
    "set once in your profile, applies to every future search automatically" pattern as Steam
    library exclusion (Phase 6). `owned_platforms` column on `user_preferences`, its own
    `GET`/`PUT /profile/owned-platforms` endpoints deliberately separate from
    `GET`/`PUT /profile/preferences` (that endpoint replaces `hard_filters`/`soft_preferences`
    wholesale on every save - folding an unrelated field in would mean saving one from one page
    silently clobbers the other's last-saved value). `services/scoring.py
    exclude_unplayable_platforms` wired into `/recommendations` the same way Steam exclusion is -
    optional signed-in user, anonymous search unaffected.
  - The platform picker (home page filter form, and now this profile section) also got a UX
    pass in the same batch of work: all 26 IGDB platform values were a flat, equal-weight list
    (Dreamcast next to PlayStation 5) - split into an always-shown primary set (PC, Mac, Linux,
    PlayStation 5/4, Xbox Series X|S/One, Nintendo Switch - current-gen + Switch + the PC
    ecosystem) with everything else behind "View more platforms", auto-expanding if a saved
    selection includes one of the hidden ones. Extracted into a shared `PlatformPicker` component
    once a second page needed the identical picker, rather than duplicating it.

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
