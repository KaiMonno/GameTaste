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
# in game-recommender-architecture.md section 4.
GAME_FIELDS = "id,name,summary,genres.name,platforms.name,game_modes.name,rating,rating_count,similar_games"


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
