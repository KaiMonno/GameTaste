# Syncing your local setup after this pull

This pull adds the curated-recommendation-list feature and a diversity fix for the
5 results shown per search. Run these **in order** - some steps depend on the one
before it. None of this touches your `.env` or API keys.

## 1. Update dependencies and start services

```bash
git pull

cd backend
source .venv/bin/activate
pip install -r requirements.txt   # no new deps this round, but cheap to run

docker compose up -d               # make sure Postgres/Redis are running
```

## 2. Apply the database migrations

```bash
alembic upgrade head
```

Adds two new things to your database:
- `curated_list_games` table - tracks which games are in the hand-curated recommendation set
- `igdb_collections` column - IGDB's franchise/series data (e.g. "Risk of Rain" links Risk of Rain, Risk of Rain 2, and Risk of Rain Returns together)

## 3. Backfill franchise data onto your existing catalog

```bash
python -m app.scripts.backfill_igdb_fields
```

Your games were already synced before `igdb_collections` existed, so this re-fetches
that one field from IGDB for everything already in your `games` table. **Free** -
IGDB only, no Claude calls.

## 4. Populate the curated list ⚠️ don't skip this

```bash
python -m app.scripts.sync_curated_list
```

**This is the step that's easy to miss.** Right after step 2, `curated_list_games`
exists but is *empty* - recommendations are now scoped to only this table, so
skipping this step means `/recommendations` returns **zero results**, which looks
like everything is broken.

This reads the repo-root `Game List` file and resolves each title against your
catalog (matching what's already there, pulling in anything missing via IGDB
search). **Free** - no Claude calls here either.

## 5. Catch any enrichment gaps

```bash
python -m app.scripts.enrich_games
```

No `--titles-file` needed - it's now automatically scoped to just the curated set.
**This is the only step that uses Claude credits**, and since you already ran the
big titles-file enrichment pass earlier, this should enrich close to nothing - it's
just a safety net for anything that resolved differently or is genuinely new.
Should cost well under $1 even in the worst case.

## 6. Restart your dev servers

If `uvicorn` and `npm run dev` are already running, restart them to pick up the
code changes (or they'll already auto-reload if you're using `--reload`/`next dev`).

---

## Quick cost summary

| Step | Uses Claude API? |
|---|---|
| 1-4 | No |
| 5 (`enrich_games.py`) | Yes - but should be near-zero cost for you specifically |

## What changed, if you're curious

- Recommendations now only ever come from the hand-curated `Game List`, not the
  broader IGDB-synced catalog
- Every search now returns exactly 5 results, chosen for variety (not just the
  raw top 5 by score) - see `services/scoring.py` `select_diverse_results`
- The "minimum review score" filter was removed
- Franchise/series sameness (e.g. sequels) now strongly discourages two entries
  from the same series both showing up in the same 5 results
