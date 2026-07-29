from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GuildConfigRepository(Protocol):
    """Persistencia da configuracao por servidor (`GuildConfig` no backend).

    `YunoAPI` e a unica implementacao hoje (fala HTTP com o backend FastAPI --
    e o "ApiRepository" do plano de fundacao). Self-host troca esse import por
    uma classe que leia/escreva local ou outro backend; os ~20 call sites que
    recebem `api` via `self.api`/`self.bot.api` nao mudam, porque Python
    resolve por estrutura, nao por heranca.
    """

    async def get_guild_config(self, guild_id: int, *, force: bool = False) -> dict[str, Any]: ...

    async def save_guild_config(self, guild_id: int, config: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class LicenseProvider(Protocol):
    """Validacao de licenca. `YunoAPI` tambem cobre este papel hoje (o
    "RemoteLicenseProvider" do plano) -- self-host precisaria de uma fonte de
    licenca diferente (arquivo local, heartbeat, etc.), sem tocar quem chama.
    """

    async def validate_license(self, guild_id: int) -> dict[str, Any]: ...
