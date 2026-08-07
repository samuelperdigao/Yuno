from typing import Any

import httpx

from yuno_bot.cache import TTLCache
from yuno_bot.config import get_settings


class ControlPlaneConflict(httpx.HTTPStatusError):
    def __init__(self, message: str, *, request: httpx.Request, response: httpx.Response, current_revision: int):
        super().__init__(message, request=request, response=response)
        self.current_revision = current_revision


class YunoAPI:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.api_base_url.rstrip("/")
        self.headers = {"x-yuno-bot-token": settings.bot_internal_token}
        # O cache mora aqui, e nao numa camada acima, porque views e modals
        # recebem o `api` e nao o bot — colocar por fora exigiria alterar os 20
        # pontos que leem a config e bastaria esquecer um para o ganho sumir.
        self._guild_config_cache: TTLCache[dict[str, Any]] = TTLCache(
            settings.guild_config_cache_ttl
        )

    async def validate_license(self, guild_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/licenses/validate",
                headers=self.headers,
                json={"guild_id": str(guild_id)},
            )
            response.raise_for_status()
            return response.json()

    async def get_guild_config(self, guild_id: int, *, force: bool = False) -> dict[str, Any]:
        """Config do servidor, servida do cache quando vigente.

        `force=True` para fluxos que precisam do estado real e nao do recente —
        `/yuno diagnostico` e o caso: diagnostico com dado velho manda o cliente
        atras do problema errado.
        """
        if force:
            self._guild_config_cache.invalidate(guild_id)
        return await self._guild_config_cache.get_or_fetch(
            guild_id, lambda: self._fetch_guild_config(guild_id)
        )

    async def _fetch_guild_config(self, guild_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/guilds/{guild_id}/config",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def save_guild_config(
        self,
        guild_id: int,
        config: dict[str, Any],
        *,
        actor_id: int | str | None = None,
    ) -> dict[str, Any]:
        headers = dict(self.headers)
        if actor_id is not None:
            headers["x-yuno-actor-id"] = str(actor_id)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/internal/guilds/{guild_id}/config",
                headers=headers,
                json=config,
            )
            response.raise_for_status()
            data = response.json()

        # A resposta do PUT e o estado novo: popular o cache com ela evita que a
        # proxima leitura pegue a versao antiga e evita um GET desnecessario.
        # Se o PUT falhou, nada e tocado — o cache antigo continua correto.
        self._guild_config_cache.set(guild_id, data)
        return data

    async def get_module_config_state(
        self,
        guild_id: int,
        module_key: str,
        *,
        actor_id: int | str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/control-plane/guilds/{guild_id}/modules/{module_key}",
                headers={**self.headers, "x-yuno-actor-id": str(actor_id)},
            )
            response.raise_for_status()
            return response.json()

    async def save_module_config_draft(
        self,
        guild_id: int,
        module_key: str,
        *,
        actor_id: int | str,
        expected_revision: int,
        schema_version: int,
        draft_data: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/internal/control-plane/guilds/{guild_id}/modules/{module_key}/draft",
                headers={**self.headers, "x-yuno-actor-id": str(actor_id)},
                json={
                    "expected_revision": expected_revision,
                    "schema_version": schema_version,
                    "draft_data": draft_data,
                },
            )
            self._raise_control_plane_status(response)
            return response.json()

    async def publish_module_config(
        self,
        guild_id: int,
        module_key: str,
        *,
        actor_id: int | str,
        expected_revision: int,
        schema_version: int,
        projection: dict[str, Any],
        panel_refs: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/control-plane/guilds/{guild_id}/modules/{module_key}/publish",
                headers={**self.headers, "x-yuno-actor-id": str(actor_id)},
                json={
                    "expected_revision": expected_revision,
                    "schema_version": schema_version,
                    "projection": projection,
                    "panel_refs": panel_refs,
                },
            )
            self._raise_control_plane_status(response)
            data = response.json()
        self._guild_config_cache.invalidate(guild_id)
        return data

    @staticmethod
    def _raise_control_plane_status(response: httpx.Response) -> None:
        if response.status_code != 409:
            response.raise_for_status()
            return
        payload = response.json().get("detail") or {}
        current_revision = int(payload.get("current_revision", 0))
        raise ControlPlaneConflict(
            "Conflito de revisao do Control Plane.",
            request=response.request,
            response=response,
            current_revision=current_revision,
        )

    def cache_stats(self) -> dict[str, Any]:
        return self._guild_config_cache.stats()

    async def upsert_ausencia(
        self,
        *,
        guild_id: int,
        user_id: int,
        nome: str,
        dias: int,
        motivo: str,
        inicio: str,
        fim: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/guilds/{guild_id}/ausencias",
                headers=self.headers,
                json={
                    "user_id": str(user_id),
                    "nome": nome,
                    "dias": dias,
                    "motivo": motivo,
                    "inicio": inicio,
                    "fim": fim,
                },
            )
            response.raise_for_status()
            return response.json()

    async def list_ausencias(
        self,
        guild_id: int,
        *,
        active_only: bool = False,
        pending_notice_only: bool = False,
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/guilds/{guild_id}/ausencias",
                headers=self.headers,
                params={"active_only": active_only, "pending_notice_only": pending_notice_only},
            )
            response.raise_for_status()
            return response.json()

    async def update_ausencia_message(self, *, guild_id: int, user_id: int, message_id: int | str | None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/internal/guilds/{guild_id}/ausencias/{user_id}/message",
                headers=self.headers,
                json={"message_id": str(message_id) if message_id else None},
            )
            response.raise_for_status()
            return response.json()

    async def mark_ausencia_avisado(self, *, guild_id: int, user_id: int | str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/internal/guilds/{guild_id}/ausencias/{user_id}/avisado",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def check_permission(
        self,
        *,
        guild_id: int,
        module: str,
        command: str,
        role_ids: list[int],
        channel_id: int | None,
        category_id: int | None,
    ) -> tuple[bool, str]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/permissions/check",
                headers=self.headers,
                json={
                    "guild_id": str(guild_id),
                    "module": module,
                    "command": command,
                    "user_role_ids": [str(role_id) for role_id in role_ids],
                    "channel_id": str(channel_id) if channel_id else None,
                    "category_id": str(category_id) if category_id else None,
                },
            )
            response.raise_for_status()
            data = response.json()
            return bool(data["allowed"]), data["reason"]

    async def create_record(
        self,
        *,
        module: str,
        guild_id: int,
        title: str,
        requester_id: int,
        channel_id: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/systems/{module}/records",
                headers=self.headers,
                json={
                    "guild_id": str(guild_id),
                    "title": title,
                    "requester_id": str(requester_id),
                    "channel_id": str(channel_id) if channel_id else None,
                    "payload": payload,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_record(self, *, module: str, record_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/systems/{module}/records/{record_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def patch_record(self, *, module: str, record_id: int, status: str, reviewer_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/systems/{module}/records/{record_id}",
                headers=self.headers,
                json={
                    "status": status,
                    "reviewer_id": str(reviewer_id),
                    "payload": payload or {},
                },
            )
            response.raise_for_status()
            return response.json()

    async def save_farm_ticket_config(self, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/config",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def get_farm_ticket_config(self, guild_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/config",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def save_farm_weekly_goal(self, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/goals",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def get_farm_weekly_goal(self, guild_id: int, week_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/goals/{week_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_farm_weekly_ranking(self, guild_id: int, week_id: str, *, limit: int = 10) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/ranking/{week_id}",
                headers=self.headers,
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()

    async def reserve_farm_ticket(self, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/tickets/reserve",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def get_active_farm_ticket(self, *, guild_id: int, week_id: str, user_id: int) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/guilds/{guild_id}/tickets/active",
                headers=self.headers,
                params={"week_id": week_id, "user_id": str(user_id)},
            )
            response.raise_for_status()
            return response.json()

    async def get_farm_ticket(self, ticket_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def set_farm_ticket_channel(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/channel",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def cancel_farm_ticket(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/cancel",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def create_farm_ticket_entry(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/entries",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def assign_farm_ticket(self, ticket_id: int, actor_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/assign",
                headers=self.headers,
                json={"actor_id": str(actor_id)},
            )
            response.raise_for_status()
            return response.json()

    async def review_farm_ticket_entry(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/review",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def approve_farm_ticket(self, ticket_id: int, actor_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/approve",
                headers=self.headers,
                json={"actor_id": str(actor_id)},
            )
            response.raise_for_status()
            return response.json()

    async def finalize_farm_ticket(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/finalize",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def delete_farm_ticket(self, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/tickets/{ticket_id}/delete",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def get_pending_farm_ticket_logs(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/actions/pending-logs",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def mark_farm_ticket_log_sent(self, action_id: int, log_message_id: int | None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/actions/{action_id}/log-sent",
                headers=self.headers,
                json={"log_message_id": str(log_message_id) if log_message_id else None},
            )
            response.raise_for_status()
            return response.json()

    async def mark_farm_ticket_log_failed(self, action_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/farm-tickets/actions/{action_id}/log-failed",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_stale_farm_tickets(self, current_week_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/maintenance/stale-tickets",
                headers=self.headers,
                params={"current_week_id": current_week_id},
            )
            response.raise_for_status()
            return response.json()

    async def get_deletable_farm_tickets(self, current_week_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/farm-tickets/maintenance/deletable-tickets",
                headers=self.headers,
                params={"current_week_id": current_week_id},
            )
            response.raise_for_status()
            return response.json()
