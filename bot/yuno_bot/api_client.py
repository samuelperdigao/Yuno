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
