from dataclasses import dataclass
from typing import Any

import httpx

from yuno_bot.config import get_settings


class ParceriaDuplicadaError(Exception):
    """Ja existe parceria registrada com esse nome de familia neste servidor."""


@dataclass(frozen=True)
class ParceriaConfig:
    guild_id: str
    parceria_category_id: int | None
    parceria_registrar_channel_id: int
    parceria_ativas_channel_id: int
    parceria_panel_message_id: int | None


class ParceriasRepository:
    """Cliente HTTP para `/internal/parcerias` no backend.

    Ate esta classe migrar, o estado de parcerias vivia num SQLite local no
    container do bot e sumia a cada redeploy (debito tecnico #2). Os metodos de
    leitura tratam falha de rede/licenca como "sem dado" -- mesmo
    comportamento que o SQLite tinha ao nao encontrar uma linha -- porque as
    chamadas ja tratam `None`/lista vazia como "nao configurado". As escritas
    propagam o erro: quem cria ou edita uma parceria precisa saber que falhou.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.api_base_url.rstrip("/")
        self.headers = {"x-yuno-bot-token": settings.bot_internal_token}

    async def get_config(self, guild_id: int) -> ParceriaConfig | None:
        data = await self._get_lenient(f"/internal/parcerias/guilds/{guild_id}/config")
        if not data:
            return None
        return ParceriaConfig(
            guild_id=data["guild_id"],
            parceria_category_id=int(data["category_id"]) if data.get("category_id") else None,
            parceria_registrar_channel_id=int(data["registrar_channel_id"]),
            parceria_ativas_channel_id=int(data["ativas_channel_id"]),
            parceria_panel_message_id=int(data["panel_message_id"]) if data.get("panel_message_id") else None,
        )

    async def upsert_config(
        self,
        *,
        guild_id: int,
        category_id: int | None,
        registrar_channel_id: int,
        ativas_channel_id: int,
        panel_message_id: int | None,
    ) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/internal/parcerias/guilds/{guild_id}/config",
                headers=self.headers,
                json={
                    "category_id": str(category_id) if category_id else None,
                    "registrar_channel_id": str(registrar_channel_id),
                    "ativas_channel_id": str(ativas_channel_id),
                    "panel_message_id": str(panel_message_id) if panel_message_id else None,
                },
            )
            response.raise_for_status()

    async def find_by_name(self, guild_id: int, nome_familia: str) -> dict[str, Any] | None:
        return await self._get_lenient(f"/internal/parcerias/guilds/{guild_id}/by-name", params={"nome_familia": nome_familia})

    async def name_exists_for_other(self, guild_id: int, nome_familia: str, parceria_id: int) -> bool:
        data = await self._get_lenient(
            f"/internal/parcerias/guilds/{guild_id}/name-exists",
            params={"nome_familia": nome_familia, "exclude_id": parceria_id},
        )
        return bool(data and data.get("exists"))

    async def list_active(self, guild_id: int) -> list[dict[str, Any]]:
        return await self._get_lenient(f"/internal/parcerias/guilds/{guild_id}/active") or []

    async def get(self, parceria_id: int) -> dict[str, Any] | None:
        return await self._get_lenient(f"/internal/parcerias/{parceria_id}")

    async def create_parceria(
        self,
        *,
        guild_id: int,
        nome_familia: str,
        produto: str,
        contato_01: str | None,
        contato_02: str | None,
        mensagem_lista_id: int,
        nome_arquivo_imagem: str,
        registrado_por: int,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/parcerias/guilds/{guild_id}",
                headers=self.headers,
                json={
                    "nome_familia": nome_familia,
                    "produto": produto,
                    "contato_01": contato_01,
                    "contato_02": contato_02,
                    "mensagem_lista_id": str(mensagem_lista_id),
                    "nome_arquivo_imagem": nome_arquivo_imagem,
                    "registrado_por": str(registrado_por),
                },
            )
            _raise_duplicada_or_status(response)
            return response.json()

    async def update_details(
        self,
        *,
        parceria_id: int,
        nome_familia: str,
        produto: str,
        contato_01: str | None,
        contato_02: str | None,
    ) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/internal/parcerias/{parceria_id}",
                headers=self.headers,
                json={
                    "nome_familia": nome_familia,
                    "produto": produto,
                    "contato_01": contato_01,
                    "contato_02": contato_02,
                },
            )
            _raise_duplicada_or_status(response)
            return response.json()

    async def update_image(self, *, parceria_id: int, nome_arquivo_imagem: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/internal/parcerias/{parceria_id}/imagem",
                headers=self.headers,
                json={"nome_arquivo_imagem": nome_arquivo_imagem},
            )
            response.raise_for_status()
            return response.json()

    async def deactivate(self, parceria_id: int) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/internal/parcerias/{parceria_id}/desativar", headers=self.headers)
            response.raise_for_status()

    async def _get_lenient(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}{path}", headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError:
            return None


def _raise_duplicada_or_status(response: httpx.Response) -> None:
    if response.status_code == 409:
        raise ParceriaDuplicadaError
    response.raise_for_status()
