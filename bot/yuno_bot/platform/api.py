from __future__ import annotations

from typing import Any

import httpx


class PlatformAPIClient:
    def __init__(self, *, base_url: str, headers: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        actor_id: int | str | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        headers = dict(self.headers)
        if actor_id is not None:
            headers["x-yuno-actor-id"] = str(actor_id)
        if correlation_id:
            headers["x-yuno-correlation-id"] = correlation_id
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method, f"{self.base_url}/internal/platform{path}", headers=headers, json=json, params=params
            )
            response.raise_for_status()
            return response.json()

    async def manifest(self) -> dict:
        return await self._request("GET", "/manifest")

    async def get_guild_profile(self, guild_id: int) -> dict:
        return await self._request("GET", f"/guilds/{guild_id}/profile")

    async def save_guild_profile(
        self, guild_id: int, profile: dict, *, actor: Any
    ) -> dict:
        actor_id = actor.user_id
        return await self._request(
            "PUT",
            f"/guilds/{guild_id}/profile",
            json={**profile, "actor": actor.as_payload()},
            actor_id=actor_id,
            correlation_id=actor.correlation_id,
        )

    async def save_admin_roles(
        self, guild_id: int, role_ids: list[int], *, actor: Any
    ) -> dict:
        return await self._request(
            "PUT",
            f"/guilds/{guild_id}/admin-roles",
            json={"role_ids": [str(item) for item in role_ids], "actor": actor.as_payload()},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def module_instance(self, guild_id: int, module_key: str) -> dict:
        return await self._request("GET", f"/guilds/{guild_id}/modules/{module_key}")

    async def update_lifecycle(
        self,
        guild_id: int,
        module_key: str,
        *,
        lifecycle: str,
        expected_lifecycle: str,
        actor: Any,
        reason: str | None = None,
    ) -> dict:
        return await self._request(
            "PUT",
            f"/guilds/{guild_id}/modules/{module_key}/lifecycle",
            json={
                "lifecycle": lifecycle,
                "expected_lifecycle": expected_lifecycle,
                "reason": reason,
                "actor": actor.as_payload(),
            },
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def configuration_draft(self, guild_id: int, module_key: str) -> dict:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/{module_key}/configuration/draft"
        )

    async def save_configuration_draft(
        self, guild_id: int, module_key: str, payload: dict, *, actor: Any
    ) -> dict:
        return await self._request(
            "PUT",
            f"/guilds/{guild_id}/modules/{module_key}/configuration/draft",
            json={**payload, "actor": actor.as_payload()},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def publish_configuration(
        self, guild_id: int, module_key: str, payload: dict, *, actor: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/{module_key}/configuration/publish",
            json={**payload, "actor": actor.as_payload()},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def effective_configuration(self, guild_id: int, module_key: str) -> dict:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/{module_key}/configuration/effective"
        )

    async def rollback_configuration(
        self, guild_id: int, module_key: str, payload: dict, *, actor: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/{module_key}/configuration/rollback",
            json={**payload, "actor": actor.as_payload()},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def diagnostics(self, guild_id: int, module_key: str) -> list[dict]:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/{module_key}/diagnostics"
        )

    async def audit(self, guild_id: int, *, module_key: str | None = None) -> list[dict]:
        params = {"module_key": module_key} if module_key else None
        return await self._request("GET", f"/guilds/{guild_id}/audit", params=params)

    async def panel_by_message(self, guild_id: int, channel_id: int, message_id: int) -> dict:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/panels/by-message",
            params={"channel_id": str(channel_id), "message_id": str(message_id)},
        )

    async def ensure_panel(
        self, guild_id: int, module_key: str, payload: dict, *, actor_id: int | str, correlation_id: str
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/{module_key}/panels",
            json=payload,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    async def update_panel(
        self, guild_id: int, panel_id: str, payload: dict, *, actor_id: int | str, correlation_id: str
    ) -> dict:
        return await self._request(
            "PATCH",
            f"/guilds/{guild_id}/panels/{panel_id}",
            json=payload,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    async def authorize(self, guild_id: int, module_key: str, payload: dict) -> dict:
        return await self._request(
            "POST", f"/guilds/{guild_id}/modules/{module_key}/authorize", json=payload
        )

    async def begin_interaction(self, guild_id: int, payload: dict) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/interactions/begin", json=payload)

    async def finish_interaction(
        self, guild_id: int, receipt_id: str, *, result: dict, error: str | None = None
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/interactions/{receipt_id}/finish",
            json={"result": result, "error": error},
        )

    async def claim_tasks(self, worker_id: str, *, limit: int = 10) -> list[dict]:
        return await self._request(
            "POST", "/automation/tasks/claim", json={"worker_id": worker_id, "limit": limit, "lease_seconds": 60}
        )

    async def schedule_task(
        self, guild_id: int, module_key: str, payload: dict
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/{module_key}/automation/tasks",
            json=payload,
        )

    async def complete_task(self, item: dict, worker_id: str, result: dict) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{item['guild_id']}/automation/tasks/{item['id']}/complete",
            json={"worker_id": worker_id, "result": result},
        )

    async def fail_task(self, item: dict, worker_id: str, error: str) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{item['guild_id']}/automation/tasks/{item['id']}/fail",
            json={"worker_id": worker_id, "error": error},
        )

    async def claim_deliveries(self, worker_id: str, *, limit: int = 10) -> list[dict]:
        return await self._request(
            "POST", "/deliveries/claim", json={"worker_id": worker_id, "limit": limit, "lease_seconds": 60}
        )

    async def complete_delivery(self, item: dict, worker_id: str, external_id: str | None) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{item['guild_id']}/deliveries/{item['id']}/complete",
            json={"worker_id": worker_id, "external_id": external_id},
        )

    async def fail_delivery(self, item: dict, worker_id: str, error: str) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{item['guild_id']}/deliveries/{item['id']}/fail",
            json={"worker_id": worker_id, "error": error},
        )

    async def registration_config(self, guild_id: int) -> dict:
        return await self._request("GET", f"/guilds/{guild_id}/modules/registration/config")

    async def registration_submit(
        self,
        guild_id: int,
        registration: dict,
        *,
        actor: Any,
        panel_config_version: int | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests",
            json={
                "actor": actor.as_payload(),
                "registration": registration,
                "panel_config_version": panel_config_version,
            },
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_request(self, guild_id: int, request_id: str) -> dict:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/registration/requests/{request_id}"
        )

    async def registration_claim(
        self, guild_id: int, request_id: str, *, actor: Any, operation_token: str | None = None
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/claim",
            json={"actor": actor.as_payload(), "operation_token": operation_token},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_preflight(
        self, guild_id: int, request_id: str, payload: dict, *, actor: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/preflight",
            json={"actor": actor.as_payload(), **payload},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_step(
        self, guild_id: int, request_id: str, operation_token: str, step: str, *, actor: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/step",
            json={"actor": actor.as_payload(), "operation_token": operation_token, "step": step},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_complete(
        self, guild_id: int, request_id: str, operation_token: str, *, actor: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/complete",
            json={"actor": actor.as_payload(), "operation_token": operation_token},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_release(
        self,
        guild_id: int,
        request_id: str,
        operation_token: str,
        *,
        actor: Any,
        compensated: bool,
        error_code: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/release",
            json={
                "actor": actor.as_payload(),
                "operation_token": operation_token,
                "compensated": compensated,
                "error_code": error_code,
            },
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_reject(
        self, guild_id: int, request_id: str, reason: str, *, actor: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/reject",
            json={"actor": actor.as_payload(), "reason": reason},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_attach_review_message(
        self,
        guild_id: int,
        request_id: str,
        channel_id: int,
        message_id: int,
        *,
        actor: Any,
    ) -> dict:
        return await self._request(
            "PATCH",
            f"/guilds/{guild_id}/modules/registration/requests/{request_id}/review-message",
            json={
                "actor": actor.as_payload(),
                "channel_id": str(channel_id),
                "message_id": str(message_id),
            },
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def registration_stale(self, guild_id: int) -> list[dict]:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/registration/recovery/stale"
        )

    async def registration_deactivate_member(
        self, guild_id: int, discord_user_id: int, *, actor: Any
    ) -> dict | None:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/modules/registration/members/{discord_user_id}/deactivate",
            json={"actor": actor.as_payload()},
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )

    async def farm_products(self, guild_id: int) -> list[dict]:
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/products")

    async def farm_create_product(self, guild_id: int, product: dict, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/products", json={"actor": actor.as_payload(), "product": product}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_archive_product(self, guild_id: int, product_id: int, revision: int, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/products/{product_id}/archive", json={"actor": actor.as_payload(), "expected_revision": revision}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_templates(self, guild_id: int) -> list[dict]:
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/templates")

    async def farm_create_template(self, guild_id: int, template: dict, *, actor: Any, source_template_id: int | None = None) -> dict:
        path = f"/guilds/{guild_id}/modules/farm/templates"
        if source_template_id is not None:
            path += f"/{source_template_id}/versions"
        return await self._request("POST", path, json={"actor": actor.as_payload(), "template": template}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_activate_template(self, guild_id: int, template_id: int, revision: int, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/templates/{template_id}/activate", json={"actor": actor.as_payload(), "expected_revision": revision}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_archive_template(self, guild_id: int, template_id: int, revision: int, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/templates/{template_id}/archive", json={"actor": actor.as_payload(), "expected_revision": revision}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_cycles(self, guild_id: int) -> list[dict]:
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/cycles")

    async def farm_create_cycle(self, guild_id: int, cycle: dict, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/cycles", json={"actor": actor.as_payload(), "cycle": cycle}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_schedule_cycle(self, guild_id: int, cycle_id: int, revision: int, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/schedule", json={"actor": actor.as_payload(), "expected_revision": revision}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_assign_participant(self, guild_id: int, cycle_id: int, member_id: int, member_display_name: str, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/participants", json={"actor": actor.as_payload(), "member_id": str(member_id), "member_display_name": member_display_name}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_transition_cycle(self, guild_id: int, cycle_id: int, revision: int, action: str, *, actor: Any, reason: str | None = None) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/{action}", json={"actor": actor.as_payload(), "expected_revision": revision, "reason": reason}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_cycle_tickets(self, guild_id: int, *, cycle_id: int | None = None, member_id: int | str | None = None) -> list[dict]:
        params = {key: value for key, value in {"cycle_id": cycle_id, "member_id": member_id}.items() if value is not None}
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/tickets", params=params or None)

    async def farm_ticket(self, guild_id: int, ticket_id: int) -> dict:
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/tickets/{ticket_id}")

    async def farm_open_ticket(self, guild_id: int, cycle_id: int, member_id: int, member_display_name: str, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/tickets", json={"actor": actor.as_payload(resource_owner_id=str(member_id)), "member_id": str(member_id), "member_display_name": member_display_name}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_progress(self, guild_id: int, ticket_id: int) -> dict:
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/tickets/{ticket_id}/progress")

    async def farm_submit(self, guild_id: int, ticket_id: int, submission: dict, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/tickets/{ticket_id}/submissions", json={"actor": actor.as_payload(resource_owner_id=str(actor.user_id)), "submission": submission}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_review_queue(self, guild_id: int, *, cycle_id: int | None = None) -> list[dict]:
        return await self._request("GET", f"/guilds/{guild_id}/modules/farm/review-queue", params={"cycle_id": cycle_id} if cycle_id is not None else None)

    async def farm_review(self, guild_id: int, submission_id: int, review: dict, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/submissions/{submission_id}/review", json={"actor": actor.as_payload(), "review": review}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def farm_inventory(self, guild_id: int, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/farm/inventory", json={"actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def run_farm_job(self, item: dict) -> dict:
        payload = {**(item.get("payload") or {}), "correlation_id": item.get("correlation_id") or item["id"]}
        return await self._request("POST", f"/guilds/{item['guild_id']}/modules/farm/jobs/{item['key']}", json=payload)

    async def start_migration(self, guild_id: int, module_key: str, migration_key: str, *, actor: Any, target_mode: str = "domain") -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/modules/{module_key}/migrations", json={"migration_key": migration_key, "target_mode": target_mode, "actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def update_migration(self, guild_id: int, run_id: str, payload: dict, *, actor: Any) -> dict:
        return await self._request("PATCH", f"/guilds/{guild_id}/migrations/{run_id}", json={**payload, "actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def cutover_migration(self, guild_id: int, run_id: str, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/migrations/{run_id}/cutover", json={"actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)

    async def rollback_migration(self, guild_id: int, run_id: str, *, actor: Any) -> dict:
        return await self._request("POST", f"/guilds/{guild_id}/migrations/{run_id}/rollback", json={"actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)
