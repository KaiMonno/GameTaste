# GameTaste

AI game recommender. See [game-recommender-mvp-plan.md](game-recommender-mvp-plan.md) and
[game-recommender-architecture.md](game-recommender-architecture.md) for the full plan and the
reasoning behind every decision - both are kept current, phase by phase, as the single source of
truth for *why* something works the way it does, not just *what* the code does.

**Current state: Phases 1-6 are done**, plus a minimal manual "Already played" exclusion button
(folded into Phase 6, see mvp-plan.md). That's the full core loop (hard filters → soft-score
ranking → diversity selection → live LLM "why you'll like it" blurbs) *and* the full profile
system (Clerk accounts, saved preference defaults, wishlist, Steam library import via OpenID
sign-in or a pasted profile URL, manual "Already played" marking) - all working end to end,
signed-in or anonymous. Not yet: Phase 7 (extended profile / PC specs), Phase 8 (Backloggd
import), and Celery/cron scheduling (the sync/enrich/backfill scripts are still run by hand).
If you're picking this up fresh, read **"Gotchas found the hard way"** below before you start -
every one of them cost real debugging time once already.

## Layout

```
backend/    FastAPI + SQLAlchemy + Alembic + IGDB/HLTB/Claude clients + sync scripts
frontend/   Next.js filter form + results list
```

## Setting up on a new machine (from a fresh clone)

**Prerequisites:**
- Docker Desktop (or another Docker runtime) — for Postgres + Redis
- Python **3.10+** (the code uses `X | None` type syntax, which older Pythons reject).
  Check with `python3 --version`. If your default `python3` is older (e.g. Anaconda ships
  3.9), install a newer one and call it explicitly:
  - macOS: `brew install python@3.12`, then use `python3.12` below
  - Linux: `sudo apt install python3.12 python3.12-venv` (or your distro's equivalent)
- Node 18+ and npm (`node --version`)
- Git, and SSH access to `git@github.com:KaiMonno/GameTaste.git` if you'll push

**Steps:**

1. **Clone and enter the repo:**
   ```
   git clone git@github.com:KaiMonno/GameTaste.git
   cd GameTaste
   ```

2. **Start Postgres + Redis:**
   ```
   docker compose up -d
   ```
   This maps Postgres to **host port 5434**, not the default 5432 — deliberately, so it
   doesn't collide with a system-wide Postgres install some machines already have running
   on 5432. If `docker compose up` fails with a port-in-use error anyway, something else is
   using 5434 or 6379 on your machine; change the host-side port in `docker-compose.yml` and
   update `backend/.env` to match.

3. **Backend:**
   ```
   cd backend
   python3.12 -m venv .venv   # or python3.11/python3.10 - whatever 3.10+ you have
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in IGDB_CLIENT_ID/SECRET and ANTHROPIC_API_KEY (see below)
   alembic upgrade head
   uvicorn app.main:app --reload
   ```
   API is up at http://localhost:8000 (docs at `/docs`).

   > **macOS + python.org-installed Python:** if any script later fails with
   > `SSLCertVerificationError: unable to get local issuer certificate`, that Python build
   > has no CA bundle wired up. Fix once with:
   > `open "/Applications/Python 3.12/Install Certificates.command"` (adjust the version in
   > the path to whatever you installed). This isn't needed for Homebrew-installed Python.

   **Tests:** `cd backend && pytest` runs everything under `tests/`. Most tests are pure unit
   tests (no DB needed); `tests/test_recommendations_integration.py` exercises the real
   scoring engine against the dev Postgres catalog and skips itself gracefully if that isn't
   reachable/seeded rather than failing the whole run.

4. **Frontend:**
   ```
   cd frontend
   npm install
   cp .env.example .env.local
   npm run dev
   ```
   App is up at http://localhost:3000.

5. **Get your own API keys/accounts.** None of these are shared between developers - each of you
   registers your own, in your own `backend/.env`/`frontend/.env.local` (see each file's
   `.env.example` for every var name):
   - **IGDB/Twitch** (`IGDB_CLIENT_ID`/`SECRET`): https://api-docs.igdb.com/#account-creation -
     needed for `sync_igdb.py` and anything that touches the catalog.
   - **Anthropic** (`ANTHROPIC_API_KEY`): https://console.anthropic.com - needed for enrichment
     and the live per-search explanations. Costs real money per call; see mvp-plan.md Phase 2/4
     for measured per-call costs before running enrichment at scale.
   - **Clerk** (`CLERK_SECRET_KEY` + frontend's `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`/
     `CLERK_SECRET_KEY`): https://clerk.com - free, create your own application, API Keys page.
     Required for accounts/wishlist/Steam import/preferences - without it every `/profile/*` and
     `/wishlist/*` endpoint 500s (fails closed, not open - see "Gotchas" below) and anonymous
     search is all that works.
   - **Steam Web API** (`STEAM_API_KEY`): https://steamcommunity.com/dev/apikey - free, needed
     for Steam library import. *After* you've populated `games` (see "What to do first" below -
     this does nothing useful against an empty table), run
     `python -m app.scripts.backfill_igdb_fields` once so those rows get a `steam_appid` to match
     against (new rows get it automatically from then on via `sync_igdb.py`/`enrich_games.py`).

Everything above — the async SQLAlchemy extra, the pinned `howlongtobeatpy` version that
actually works against HLTB's current site — is already correct in `requirements.txt`, so a
plain `pip install -r requirements.txt` on a fresh machine should not hit the errors that were
worked through while first building this (see git history / commit messages if curious).

## Gotchas found the hard way

Every one of these cost real debugging time once already - check this list before assuming
something's broken.

- **The backend caches `.env` for the whole process lifetime.** `get_settings()` is
  `lru_cache`'d, so editing `backend/.env` (a new key, a changed value) does nothing to an
  already-running `uvicorn` process - `--reload` only reacts to `.py` file changes, not `.env`.
  Symptom: a brand new `CLERK_SECRET_KEY`/`STEAM_API_KEY` you just set still 500s/401s as if it
  were empty. Fix: actually kill and restart `uvicorn`, every time you touch `.env`. Bit this
  project twice (Clerk, then Steam) before this line got written.
- **Don't run `npm run build` while `npm run dev` is running against the same `frontend/`.**
  Both write to `.next/` and a concurrent build corrupts the dev server's cache - symptom is a
  cryptic `Cannot find module './13.js'` (or similar numbered-chunk) error on page load. Fix:
  stop the dev server first, build, then `rm -rf .next` and restart `npm run dev` fresh. If you
  hit the error without realizing why, the same fix (stop, `rm -rf .next`, restart) resolves it
  regardless of cause.
- **A new migration needs `alembic upgrade head`, every time.** Pulling someone else's commit
  that adds a column/table doesn't apply it to *your* local Postgres - `git pull` and `alembic
  upgrade head` are two separate steps. Run the latter after every pull that touches
  `backend/alembic/versions/`.
- **Installing/upgrading one backend package can silently break another via a shared transitive
  dependency, with no error until the broken code path actually runs.** Installing
  `clerk-backend-api` once pulled in a newer `httpx` as a side effect, which silently broke the
  pinned `anthropic` SDK's internal client construction - `pip install` succeeded, the test
  suite passed (it mocks the Claude call), and the backend ran fine; only a *live* call to
  `explain_candidates` actually failed, and `/recommendations` is designed to swallow that
  failure as best-effort (same as a real Claude outage), so every search silently returned
  `why_recommended: null` with no visible error for an entire phase of work. If you add or
  upgrade any package, don't just trust `pip install` succeeding or the test suite passing -
  also do one live smoke test of anything that constructs an API client (Anthropic, Steam,
  Clerk) end to end. `requirements.txt` pins should always match what's *actually* installed
  (`pip freeze` the specific package) - check this explicitly after any install that touches a
  shared dependency like `httpx`/`pydantic`, since pip resolving a transitive bump silently is
  exactly how this one slipped through.
- **No shared database between developers.** Each of you runs IGDB sync / HLTB match / LLM
  enrichment / the curated-list sync against your *own* local Postgres - there's no way to
  "pull" another developer's catalog data via git. If recommendations come back empty or a
  game you expect is missing, that's almost always "I haven't synced/enriched/curated this game
  on my machine yet," not a code bug.

## What to do first (in order)

**Important, easy to miss:** `/recommendations` only ever returns games from the hand-curated
list (the repo-root `Game List` file → `curated_list_games` table, see mvp-plan.md Phase 3.7) -
*not* whatever the broad IGDB sync pulls in. Those are two separate population paths. Step 1
below is the one that actually matters for getting real results; step 4 (broad sync) is useful
context/tuning but isn't what `/recommendations` reads from.

1. **Get IGDB credentials**, then populate the curated set - this one script does IGDB search +
   HLTB match for every title in `Game List` in one pass (no separate HLTB step needed for these):
   ```
   cd backend && source .venv/bin/activate
   python -m app.scripts.sync_curated_list
   ```
   Re-run this after any edit to the repo-root `Game List` file - it diffs current membership
   against the file (adds newly-listed titles, removes delisted ones) rather than taking manual
   add/remove commands.

2. **Hit `/recommendations`** from the frontend (or `curl`/`/docs`) and see whether the
   hard-filter + soft-score ranking *feels* right (numeric `match_score` only so far - no
   `why_recommended`/`why_not` yet, that needs step 3). Tune `WEIGHTS` in
   [backend/app/services/scoring.py](backend/app/services/scoring.py) based on what you see.

3. **Once scoring feels right**, add your `ANTHROPIC_API_KEY` (see "Get your own API
   keys/accounts" above) and run `python -m app.scripts.enrich_games --limit 10` first - costs
   real money per call, so spot-check a small batch's accuracy before scaling up to the full
   curated set (drop `--limit` once you trust it; no args defaults to curated-only, same scope
   as `/recommendations` itself). Populates the v3 enrichment fields both `llm_enrichment.py`
   (this offline pass) and `llm_explanations.py` (the live, per-search blurbs, Phase 4) depend
   on - once this has run, `why_recommended`/`why_not` start showing up on real requests.

4. **(Optional) Broader catalog sync**, for context/tuning or future re-curation - *not* required
   for `/recommendations`, which never reads from outside the curated set:
   ```
   python -m app.scripts.sync_igdb --pages 1   # 500 most-popular games into `games`
   python -m app.scripts.match_hltb            # HLTB length for those same games
   ```
   Expect some HLTB misses — it has no official API (see mvp-plan.md §1/§5); check the logs for
   unmatched titles rather than assuming 100% coverage.

5. **Accounts/wishlist/preferences (Phase 5) and Steam import (Phase 6) are both done** and need
   no further wiring - just the Clerk/Steam keys from "Get your own API keys/accounts" above.
   Once those are set (**and the backend restarted** - see Gotchas), sign in via the header, and:
   - Save default filters from the home page, see your wishlist at `/wishlist`.
   - Import your Steam library (OpenID "Sign in through Steam" or a pasted profile URL) and
     manually mark individual games "Already played" from `/profile` - both exclude from future
     `/recommendations` results the same way.
   **Not yet:** Celery/cron scheduling — the sync/match/enrich scripts are meant to be run by
   hand for now, then promoted to a scheduled job once you trust the pipeline.

## Notes on what's deliberately stubbed

- No Celery/Arq — the "background jobs" from the architecture doc are plain scripts under
  `backend/app/scripts/`, runnable by hand or cron. Promote to Celery Beat only once you're
  actually running these on a schedule and need retries/monitoring.
- No `pgvector`/embeddings column — that's a v2 addition per the architecture doc, add it as a
  new Alembic migration when you actually build similarity search.
