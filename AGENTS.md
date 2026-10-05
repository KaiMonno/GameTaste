# Instructions for AI coding agents working in this repo

Read [README.md](README.md) first - specifically **"Gotchas found the hard way"** and **"What to
do first"**. Both sections exist because an agent (this one, in an earlier session) or a human
hit each of those issues for real and lost time to it. Don't re-discover them the hard way.

The two things most likely to cost you time if skipped:

1. **This repo has no shared database between developers.** Cloning it gets you code, not data -
   `games`, `curated_list_games`, enrichment, everyone's own `users`/`wishlist_items`/etc. all
   live in each developer's own local Postgres. If recommendations come back empty, a game is
   "missing," or a migration seems to not exist, check "What to do first" in README.md before
   assuming something is broken - it's almost always "this local DB hasn't been
   synced/enriched/migrated yet," not a code bug.
2. **`/recommendations` only returns games from the curated list**, not the broader IGDB-synced
   catalog - these are two separate population paths (see README.md "What to do first", step 1
   vs. step 4). Populating the broad catalog alone will not make `/recommendations` return
   anything.

## Where the reasoning lives, not just the code

- [README.md](README.md) - setup, current state, operational gotchas.
- [game-recommender-mvp-plan.md](game-recommender-mvp-plan.md) - the product/feature history,
  phase by phase, including decisions that were tried and reverted (e.g. popularity-as-a-
  preference, Phase 3.5→3.6) and *why*. Read the relevant phase before changing behavior in an
  area - the reasoning for why something is the way it is is almost always there, not in a code
  comment.
- [game-recommender-architecture.md](game-recommender-architecture.md) - tech stack, data flow,
  data model, what changes at each phase boundary.

Both docs are maintained as current, not historical snapshots - if you make a change that a
phase/table/decision description no longer matches, update the doc in the same commit, the way
every commit in this repo's history does. A stale doc here is treated as a bug.

## Conventions this codebase holds to (verified while working in it, not assumed)

- **Verify third-party API/SDK behavior empirically before coding against it**, the same way
  this project confirmed IGDB's `external_games.external_game_source` field (not a numeric enum
  it used to be), Steam's OpenID assoc_handle/claimed_id shape, and Clerk's `authenticate_request`
  return shape - by querying the real API or reading a real installed package's types, not by
  recalling it from training data. Several real bugs in this project's history came from an SDK
  version having moved on from what training data remembers.
- **Never estimate cost or performance numbers for LLM calls - measure them.** Every enrichment/
  explanation cost and latency figure in mvp-plan.md is a number from a real run against the real
  API, not a calculation. Do the same before reporting a number to the user.
- **A dependency install can silently break an unrelated package via a shared transitive
  dependency** (see README.md Gotchas - this is how `anthropic` broke from installing
  `clerk-backend-api`). After any `pip install`/`npm install` that isn't a leaf package with no
  shared deps, run the test suite *and* a live smoke test of anything that constructs an API
  client, not just one or the other.
- **Best-effort/graceful-degradation paths can hide real bugs for a long time.**
  `/recommendations` is designed to swallow an `explain_candidates` failure and return numeric-
  only results rather than fail the request - exactly the behavior that let a real regression
  (the dependency break above) silently return `null` explanations for an entire phase of work
  with no visible error. When touching a best-effort path, check backend logs for what it's
  actually swallowing, don't just trust that "no error reached the user" means "nothing is wrong."
