"""IGDB API client (auth via Twitch OAuth client-credentials flow).

Docs: https://api-docs.igdb.com/
Rate limit: 4 req/sec - this client does not batch/throttle yet; the sync
script is the only caller for now and stays well under that on a nightly run.
"""

import time

import httpx

from app.config import get_settings

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_BASE_URL = "https://api.igdb.com/v4"

# Fields pulled per game - matches the "games" table columns sourced from IGDB
# in game-recommender-architecture.md section 4. `game_type` is IGDB's own
# game-vs-DLC-vs-expansion/etc classification (0 = main_game; this field was
# named `category` in older IGDB docs/versions, confirmed renamed by directly
# querying `fields *` against a known expansion - it came back with
# `game_type`, not `category`); used to exclude DLC/expansions from
# recommendations by default - see services/scoring.py.
#
# `collections.name` groups a game with its direct series (confirmed via a
# live query: Risk of Rain, Risk of Rain 2, and Risk of Rain Returns all
# share collection id 6420, name "Risk of Rain") - used by
# services/scoring.py select_diverse_results to recognize same-franchise
# games as maximally similar regardless of whether their genre tags happen
# to overlap. IGDB also has a `franchises` field (broader, publisher-level
# groupings) but it came back empty for this exact case - `collections` is
# the field that actually has data for the games this matters for.
GAME_FIELDS = (
    "id,name,summary,genres.name,platforms.name,game_modes.name,rating,rating_count,"
    "similar_games,game_type,collections.name"
)


class IGDBClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.igdb_client_id
        self._client_secret = settings.igdb_client_secret
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    async def _get_access_token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TWITCH_TOKEN_URL,
                params={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._access_token = data["access_token"]
        # Refresh a minute early to avoid using a token that expires mid-request.
        self._token_expires_at = time.monotonic() + data["expires_in"] - 60
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_access_token()
        return {
            "Client-ID": self._client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def fetch_games(self, offset: int = 0, limit: int = 500) -> list[dict]:
        """Fetch a page of games, sorted by popularity (rating_count) so the
        most relevant games sync first if a run is interrupted or scoped down.
        """
        query = f"""
            fields {GAME_FIELDS};
            where rating_count != null;
            sort rating_count desc;
            limit {limit};
            offset {offset};
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{IGDB_BASE_URL}/games",
                headers=await self._headers(),
                content=query,
            )
            resp.raise_for_status()
            return resp.json()

    async def search_games(self, title: str, limit: int = 10) -> list[dict]:
        """Look up a specific title by name (IGDB's `search` apicalypse
        operator - fuzzy/relevance-ranked on IGDB's side), for pulling
        specific games into `games` on demand rather than bulk pagination.
        Deliberately no `where rating_count != null` filter here (unlike
        fetch_games) - a title-specific lookup should still find something
        like an early-access game with few/no ratings yet, not silently
        drop it. Caller is responsible for fuzzy-matching/validating the
        results against the requested title (see services/title_matching.py)
        rather than trusting IGDB's top hit blindly.
        """
        # Note: `search` and `sort` can't be combined in the same apicalypse
        # query - IGDB orders search results by its own relevance score.
        query = f"""
            search "{title}";
            fields {GAME_FIELDS};
            limit {limit};
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{IGDB_BASE_URL}/games",
                headers=await self._headers(),
                content=query,
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_by_ids(self, ids: list[int]) -> list[dict]:
        """Fetch specific games by id, not a popularity-sorted page - needed
        to backfill a newly-added IGDB-sourced field onto rows that were
        never covered by fetch_games' bulk popularity sync. `games` now
        includes titles pulled in via search_games (resolve_titles, for the
        curated list - see scripts/sync_curated_list.py), which are NOT
        necessarily IGDB's top-N-by-rating_count - re-running the bulk sync
        with more pages pulls in IGDB's actual global next-N-by-popularity,
        not specifically these already-known ids. Caller must batch for
        lists over ~500 (IGDB's own per-request limit) - see
        scripts/backfill_igdb_fields.py.
        """
        if not ids:
            return []
        id_list = ",".join(str(i) for i in ids)
        query = f"""
            fields {GAME_FIELDS};
            where id = ({id_list});
            limit {len(ids)};
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{IGDB_BASE_URL}/games",
                headers=await self._headers(),
                content=query,
            )
            resp.raise_for_status()
            return resp.json()
