# AI Game Recommender — Tech Stack & Architecture

## 1. Tech Stack Summary

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js (React) + TypeScript + Tailwind** | Good DX, easy deploy (Vercel), server-side rendering if you ever want shareable/SEO'd result pages, huge ecosystem for form-heavy UIs. |
| Backend API | **Python + FastAPI** | Async, typed, and Python has the best ecosystem for this project specifically: `howlongtobeatpy`, `rapidfuzz` (fuzzy title matching), and first-class Anthropic SDK support. Data/scraping/enrichment work is the hard part of this project — pick the language that makes *that* easy. |
| Primary database | **PostgreSQL** | Relational fit for games/users/wishlist; **pgvector** extension for embedding-based "similar to X" search later. |
| Cache / job broker | **Redis** | Caches hot queries, backs the job queue. |
| Background jobs & scheduling | **Celery (or Arq for a lighter async-native option) + Celery Beat / cron** | Nightly IGDB sync, HLTB matching, LLM enrichment batches — none of this should run inline on a user request. |
| LLM | **Claude API (Anthropic)** — used two different ways | (1) Batch enrichment: story-vs-gameplay / content warnings, cached per game. (2) Online: per-candidate "why/why not" explanations on the ~15–20 shortlisted games only. |
| External data | **IGDB API** (Twitch OAuth), **HowLongToBeat** (via `howlongtobeatpy`, unofficial), **Steam Web API** (phase 6, official) | Core game metadata + length + backlog import. |
| Auth (phase 5+) | **Clerk or Supabase Auth** (or Auth.js if you want to self-host) | Don't build auth yourself for an MVP; buy it. |
| Hosting | **Vercel (frontend) + Railway or Fly.io (API, Postgres, Redis, workers)** | Cheap, fast to set up, no need for Kubernetes at this stage. Migrate to AWS/GCP only if/when scale demands it. |

You could collapse this to a single-language stack (Node/TypeScript everywhere, e.g. NestJS backend + BullMQ instead of Celery) if you'd rather not context-switch languages. It's a legitimate choice — the main thing you'd lose is `howlongtobeatpy` and `rapidfuzz`, which have weaker JS equivalents. Python is the stronger pick specifically because of the scraping/matching/enrichment-heavy nature of this project.

---

## 2. Full Architecture

```
                                ┌───────────────────────────┐
                                │        Next.js Frontend    │
                                │  (filter form, results,    │
                                │   profile, wishlist UI)    │
                                └──────────────┬─────────────┘
                                               │ REST/JSON
                                               ▼
                                ┌───────────────────────────┐
                                │      FastAPI Backend       │
                                │  ─ /recommendations        │
                                │  ─ /games/:id              │
                                │  ─ /profile, /wishlist     │
                                │  ─ /import/steam           │
                                └───┬───────────────┬────────┘
                                    │               │
                        reads/writes│               │enqueues jobs
                                    ▼               ▼
                    ┌───────────────────────┐  ┌─────────────────────┐
                    │   PostgreSQL (+pgvec) │  │   Redis (cache +     │
                    │  games, users,        │  │   Celery/Arq broker) │
                    │  wishlist, enrichment │  └──────────┬───────────┘
                    │  cache, embeddings    │             │
                    └───────────────────────┘             ▼
                                                 ┌────────────────────────┐
                                                 │   Background Workers    │
                                                 │  ─ IGDB nightly sync    │
                                                 │  ─ HLTB match + scrape  │
                                                 │  ─ LLM enrichment batch │
                                                 │    (story/gameplay,     │
                                                 │    content warnings)    │
                                                 │  ─ Steam import job     │
                                                 └───────────┬─────────────┘
                                                             │
                                     ┌───────────────────────┼───────────────────────┐
                                     ▼                       ▼                       ▼
                              ┌────────────┐         ┌───────────────┐       ┌───────────────┐
                              │  IGDB API  │         │ HowLongToBeat │       │  Claude API    │
                              │ (Twitch    │         │ (unofficial,  │       │ (enrichment +  │
                              │  OAuth)    │         │  scrape lib)  │       │  explanations) │
                              └────────────┘         └───────────────┘       └───────────────┘
                                                                                      ▲
                                                             ┌────────────────────────┘
                                                             │ per-candidate, on-demand
                                                    (called directly from FastAPI at
                                                     query time, top N results only —
                                                     not a background job)
```

---

## 3. Data Flow

**Offline (scheduled, not user-facing):**
1. **IGDB sync job** — nightly pull of games (genres, platforms, IGDB rating, popularity, game modes, similar_games) into `games` table.
2. **HLTB match job** — for each new/updated game, fuzzy-match title against HLTB, store main/main+extra/completionist hours. Log unmatched titles for review rather than silently dropping them.
3. **LLM enrichment job** — for each game missing enrichment, one Claude call to infer story-vs-gameplay ratio and content-warning tags from IGDB summary + genre/theme + (optionally) scraped review snippets. Store with a `enriched_at` timestamp and a schema version, so you can re-run cheaply when you improve the prompt later. (Difficulty was considered here too but is out of scope entirely - no reliable ground truth, see mvp-plan.md section 1.)
4. **(v2) Embedding job** — generate an embedding per game (description + tags) into `pgvector` for similarity search beyond IGDB's limited `similar_games` field.

**Online (user-facing, request/response):**
1. User submits filters → FastAPI applies **hard filters** in SQL (genre exclude, platform, no-mobile, content-warning excludes, multiplayer requirement).
2. FastAPI computes **weighted soft-match score** in-process (length distance, review score, popularity/nichety distance, story/gameplay distance, similarity score) → ranks candidates.
3. Top ~15–20 candidates sent to Claude in a single batched call (not 15 separate calls) asking for a "why you'll like it / why you might not" per game, returned as structured JSON.
4. Response merged with the numeric % match (computed by the formula, not the LLM — keeps the ranking auditable and consistent) and returned to frontend.

**Why split it this way:** the expensive/fragile stuff (scraping, enrichment) happens once per game on a schedule; the cheap stuff (filtering, scoring) happens per query in SQL; the LLM is only invoked live for the small shortlist, keeping latency and cost bounded regardless of catalog size.

---

## 4. Data Model (core tables)

```
games
  id (igdb_id, pk)
  name, summary
  genres[], platforms[], game_modes[]      -- from IGDB
  igdb_rating, igdb_rating_count           -- score + popularity proxy
  similar_game_ids[]                       -- from IGDB
  hltb_main, hltb_main_extra, hltb_completionist
  story_gameplay_ratio                     -- LLM-enriched
  content_warnings[]                       -- LLM-enriched
  embedding (vector)                       -- v2
  enriched_at, enrichment_version

users                                      -- phase 5+
  id, auth_provider_id, created_at

user_preferences                           -- phase 5+
  user_id, default filter values (json)

wishlist                                   -- phase 5+
  user_id, game_id, added_at

user_library                               -- phase 6+
  user_id, game_id, source (steam/manual), playtime, completed_bool
```

---

## 5. Deployment Topology (MVP-appropriate, not over-built)

- **Frontend:** Vercel (Next.js) — zero-config CD from git.
- **API + workers:** Railway or Fly.io — one Postgres instance, one Redis instance, one API service, one worker service (can literally be the same container running a different command initially).
- **Secrets:** IGDB/Twitch client credentials, Anthropic API key, Steam API key — environment variables in the hosting platform, never in the repo.
- **No Kubernetes, no microservices split** at this stage — a monolithic FastAPI app with a separate worker process is enough until you have real scale reasons to split it.

---

## 6. What Changes as You Move Through Phases

- **Phase 5 (profile):** add `users`/`user_preferences` tables + hosted auth (Clerk/Supabase). No architecture change otherwise.
- **Phase 6 (Steam import):** add a Steam import worker job (`GetOwnedGames` via Steam Web API) that populates `user_library` and is joined against at query time to exclude owned/played titles.
- **Phase 7 (PC specs / consoles / controller):** these become additional **hard filters** at query time — no new infra, just more filter logic + possibly a small `pc_specs`/`min_requirements` field sourced from Steam if available.
- **v2 similarity:** swap "similarity to X" from IGDB's `similar_games` list to a proper `pgvector` cosine-similarity query once embeddings are populated — this is a drop-in replacement for that one scoring factor, not a rearchitecture.
