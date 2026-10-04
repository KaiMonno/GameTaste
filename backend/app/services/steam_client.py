"""Phase 6: Steam Web API client - resolves a user-supplied profile
identifier to a SteamID64, then pulls their owned-games list. Read-only,
no OAuth: a single server-held API key (steam_api_key) calls Steam's
public JSON API on the user's behalf, the same app-level-credential
pattern as services/igdb_client.py, not a per-user token.

Deliberately NOT "Sign in through Steam" (OpenID) - that still needs this
same API key for GetOwnedGames regardless, and would add a full OpenID
redirect/verify round trip for no benefit beyond skipping a paste; a
profile URL/vanity name/SteamID64 text field is the simpler MVP path and
is explicitly listed as acceptable in mvp-plan.md Phase 6 ("OAuth or
API-key based").
"""

import logging
import re

import httpx

from app.config import get_settings

STEAM_API_BASE = "https://api.steampowered.com"

# Steam's API takes the key as a query param with no body alternative
# (unlike Twitch's token endpoint, see igdb_client.py) - suppressing
# httpx's own INFO-level full-request-line logging is the only way to keep
# it out of logs/stdout.
logging.getLogger("httpx").setLevel(logging.WARNING)


class SteamProfileError(Exception):
    """Raised when the given identifier can't be resolved, or the profile's
    game-details privacy is set to private - both are user-fixable, not
    server errors, so routers/profile.py surfaces this as a 400, not a 500.
    """


def _extract_identifier(raw: str) -> str:
    """Accepts a bare SteamID64, a vanity name, or a full profile URL
    (steamcommunity.com/profiles/<id> or /id/<vanity>) - strips the URL
    down to just the id/vanity segment the API calls below expect.
    """
    raw = raw.strip()
    match = re.search(r"steamcommunity\.com/(?:profiles|id)/([^/?#]+)", raw, re.IGNORECASE)
    return match.group(1) if match else raw


async def resolve_steam_id64(identifier: str) -> str:
    """Resolves a vanity name or profile URL to a SteamID64. A bare
    SteamID64 (17 digits) is returned as-is without calling the API - it's
    already resolved.
    """
    identifier = _extract_identifier(identifier)
    if re.fullmatch(r"\d{17}", identifier):
        return identifier

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STEAM_API_BASE}/ISteamUser/ResolveVanityURL/v1/",
            params={"key": settings.steam_api_key, "vanityurl": identifier},
        )
        resp.raise_for_status()
        data = resp.json().get("response", {})

    if data.get("success") != 1:
        raise SteamProfileError(
            f"Couldn't find a Steam profile for {identifier!r} - check the profile URL or name"
        )
    return data["steamid"]


async def get_owned_games(steam_id64: str) -> list[tuple[int, int]]:
    """Returns [(appid, playtime_forever_minutes), ...] for games owned on
    this account. Steam returns an empty `response` (no `games` key, no
    error) when the profile's "game details" privacy is private, or the
    account owns nothing public - both look identical from this API, so we
    can only report "nothing found", not which case it was.
    """
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STEAM_API_BASE}/IPlayerService/GetOwnedGames/v1/",
            params={
                "key": settings.steam_api_key,
                "steamid": steam_id64,
                "include_appinfo": "false",
                "include_played_free_games": "true",
            },
        )
        resp.raise_for_status()
        data = resp.json().get("response", {})

    if "games" not in data:
        raise SteamProfileError(
            "No owned games visible - make sure this Steam profile and its game details are set to Public"
        )

    return [(g["appid"], g.get("playtime_forever", 0)) for g in data["games"]]
