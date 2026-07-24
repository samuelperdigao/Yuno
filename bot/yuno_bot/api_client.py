from typing import Any

import httpx

from yuno_bot.config import get_settings


class YunoAPI:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.api_base_url.rstrip("/")
        self.headers = {"x-yuno-bot-token": settings.bot_internal_token}

    async def validate_license(self, guild_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/internal/licenses/validate",
                headers=self.headers,
                json={"guild_id": str(guild_id)},
            )
            response.raise_for_status()
            return response.json()

    async def get_guild_config(self, guild_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/internal/guilds/{guild_id}/config",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def save_guild_config(self, guild_id: int, config: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(
                f"{self.base_url}/internal/guilds/{guild_id}/config",
                headers=self.headers,
                json=config,
            )
            response.raise_for_status()
            return response.json()

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
