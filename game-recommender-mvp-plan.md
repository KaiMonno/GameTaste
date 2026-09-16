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
- Filter form → hard filter → soft-score → return ranked list, no LLM blurbs yet (just numeric % match)
- This validates whether the scoring logic *feels* right before spending LLM budget on explanations

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
