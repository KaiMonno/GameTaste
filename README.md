# GameTaste

AI game recommender. See [game-recommender-mvp-plan.md](game-recommender-mvp-plan.md) and
[game-recommender-architecture.md](game-recommender-architecture.md) for the full plan — this
scaffold implements the **Phase 1-3 MVP cut**: data foundation, hard-filter + soft-score
recommendation engine, and a single-form frontend. No accounts, no Celery workers, no LLM calls
wired into the request path yet (services exist for phase 2/4, just not called from the routes).

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

4. **Frontend:**
   ```
   cd frontend
   npm install
   cp .env.example .env.local
   npm run dev
   ```
   App is up at http://localhost:3000.

5. **Get API keys before the sync scripts will work:**
   - IGDB/Twitch: https://api-docs.igdb.com/#account-creation (needed for `sync_igdb.py`)
   - Anthropic: https://console.anthropic.com (needed once you wire up phase 2/4 enrichment)

Everything above — the async SQLAlchemy extra, the pinned `howlongtobeatpy` version that
actually works against HLTB's current site — is already correct in `requirements.txt`, so a
plain `pip install -r requirements.txt` on a fresh machine should not hit the errors that were
worked through while first building this (see git history / commit messages if curious).

## What to do first (in order)

1. **Get IGDB credentials** and run the sync script against a small page to prove the pipeline:
   ```
   cd backend && source .venv/bin/activate
   python -m app.scripts.sync_igdb --pages 1
   ```
   This pulls the 500 most-popular games into `games`. Check the row count and spot-check a few
   records before scaling up.

2. **Run the HLTB matcher** on those same games:
   ```
   python -m app.scripts.match_hltb
   ```
   Expect some misses — HLTB has no official API (see mvp-plan.md §1/§5). Check the logs for
   unmatched titles rather than assuming 100% coverage.

3. **Hit `/recommendations`** from the frontend (or `curl`/`/docs`) with a small synced catalog
   and see whether the hard-filter + soft-score ranking *feels* right. This is Phase 3's whole
   point — validate scoring quality before spending any LLM budget. Tune `WEIGHTS` in
   [backend/app/services/scoring.py](backend/app/services/scoring.py) based on what you see.

4. **Only once scoring feels right**, add your `ANTHROPIC_API_KEY` and wire
   [backend/app/services/llm_enrichment.py](backend/app/services/llm_enrichment.py) into
   `scripts/enrich_games.py` (already stubbed, just needs a real run + spot-check), then wire
   [backend/app/services/llm_explanations.py](backend/app/services/llm_explanations.py) into the
   `/recommendations` route for the "why you'll like it" blurbs (Phase 4).

5. **Not yet:** accounts, wishlist, Steam import, Celery/cron scheduling. Per the MVP plan these
   come after the core loop is validated — the sync/match/enrich scripts are meant to be run by
   hand for now, then promoted to a scheduled job once you trust the pipeline.

## Notes on what's deliberately stubbed

- No Celery/Arq — the "background jobs" from the architecture doc are plain scripts under
  `backend/app/scripts/`, runnable by hand or cron. Promote to Celery Beat only once you're
  actually running these on a schedule and need retries/monitoring.
- No `pgvector`/embeddings column — that's a v2 addition per the architecture doc, add it as a
  new Alembic migration when you actually build similarity search.
- No auth — Phase 5+, add `users`/`user_preferences` tables and a hosted auth provider then.
