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

    steam_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
