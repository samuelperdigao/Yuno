from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    discord_bot_token: str
    discord_test_guild_id: int | None = None
    api_base_url: str = "http://api:8000"
    bot_internal_token: str = "development-bot"
    # TTL do cache de guild config. Curto de proposito: alteracao feita no
    # dashboard web nao invalida o cache deste processo, entao este numero e o
    # tempo maximo que o cliente espera para ver a mudanca refletida no bot.
    guild_config_cache_ttl: float = 30.0
    control_plane_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> BotSettings:
    return BotSettings()


def setup_required_message(module_name: str, legacy_instruction: str) -> str:
    if get_settings().control_plane_enabled:
        return (
            f"O módulo {module_name} ainda não está configurado. "
            "Migração para a Central pendente; peça ao administrador para acompanhar pela Central."
        )
    return legacy_instruction
