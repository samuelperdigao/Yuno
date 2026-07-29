"""Trava o contrato de self-host (0.6 do plano de fundacao).

`GuildConfigRepository` e `LicenseProvider` descrevem os dois pontos que uma
implementacao self-host precisaria reimplementar. Este teste garante que
`YunoAPI` continua satisfazendo os dois -- se um metodo for renomeado ou
removido de `YunoAPI` sem querer, e aqui que isso quebra.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.api_client import YunoAPI
from yuno_bot.interfaces import GuildConfigRepository, LicenseProvider


def test_yuno_api_satisfies_guild_config_repository_and_license_provider() -> None:
    api = YunoAPI()
    assert isinstance(api, GuildConfigRepository)
    assert isinstance(api, LicenseProvider)
