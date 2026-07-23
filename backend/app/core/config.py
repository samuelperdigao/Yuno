from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    public_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"

    database_url: str = "sqlite+aiosqlite:///./yuno.db"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = "development-secret"
    admin_token: str = "development-admin"
    bot_internal_token: str = "development-bot"

    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_redirect_uri: str = "http://localhost:8000/auth/discord/callback"

    mercado_pago_access_token: str = ""
    mercado_pago_webhook_secret: str = ""

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
