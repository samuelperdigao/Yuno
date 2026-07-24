from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    discord_bot_token: str
    discord_test_guild_id: int | None = None
    api_base_url: str = "http://api:8000"
    bot_internal_token: str = "development-bot"
    parcerias_database_path: str = "./data/parcerias.sqlite3"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> BotSettings:
    return BotSettings()
