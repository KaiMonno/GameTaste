from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://gametaste:gametaste@localhost:5434/gametaste"
    database_url_sync: str = "postgresql+psycopg2://gametaste:gametaste@localhost:5434/gametaste"
    redis_url: str = "redis://localhost:6379/0"

    igdb_client_id: str = ""
    igdb_client_secret: str = ""

    anthropic_api_key: str = ""

    # Phase 6: a single app-level key (register at
    # steamcommunity.com/dev/apikey) - see services/steam_client.py. Not a
    # per-user OAuth token.
    steam_api_key: str = ""

    # Phase 5: Clerk handles identity/sessions, we only verify the token it
    # issues - see services/auth.py. clerk_jwt_key (the PEM public key from
    # the Clerk dashboard) enables networkless verification; left empty, the
    # SDK falls back to a network call to Clerk per request, which still
    # works but adds latency. clerk_authorized_parties guards against a
    # token issued for a different frontend being replayed against this API.
    clerk_secret_key: str = ""
    clerk_jwt_key: str = ""
    clerk_authorized_parties: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
