from __future__ import annotations

from typing import Any


class FarmTicketsAPI:
    """Cliente do contrato HTTP v2, mantido dentro do modulo proprietario."""

    def __init__(self, platform_api: Any) -> None:
        self.platform_api = platform_api

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return await self.platform_api._request(method, path, **kwargs)

    async def ticket(self, guild_id: int, ticket_id: str) -> dict:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}"
        )

    async def tickets(
        self,
        guild_id: int,
        *,
        active_only: bool = True,
        reconcile_only: bool = False,
    ) -> list[dict]:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets",
            params={
                "active_only": str(active_only).lower(),
                "reconcile_only": str(reconcile_only).lower(),
            },
        )

    async def active_ticket(self, guild_id: int, member_id: int | str) -> dict | None:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/modules/farm_tickets/members/{member_id}/active-ticket",
        )

    async def owner(self, guild_id: int, ticket_id: str) -> str | None:
        ticket = await self.ticket(guild_id, ticket_id)
        return str(ticket.get("member_id") or "") or None

    async def entries(
        self, guild_id: int, ticket_id: str, *, editable_only: bool = False
    ) -> list[dict]:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/entries",
            params={"editable_only": str(editable_only).lower()},
        )

    async def channel_operation(self, guild_id: int, channel_id: int) -> dict | None:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/modules/farm_tickets/channels/{channel_id}/active-operation",
        )

    async def bindings(
        self, guild_id: int, *, ticket_id: str | None = None
    ) -> list[dict]:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/modules/farm_tickets/bindings",
            params={"ticket_id": ticket_id} if ticket_id else None,
        )

    async def upsert_binding(
        self, guild_id: int, payload: dict[str, Any], *, actor: dict[str, Any]
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/bindings",
            actor=actor,
            payload=payload,
        )

    async def binding_deleted(
        self,
        guild_id: int,
        binding_id: str,
        *,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/bindings/{binding_id}/deleted",
            actor=actor,
            payload={"idempotency_key": idempotency_key},
        )

    async def claim_proof(
        self,
        guild_id: int,
        ticket_id: str,
        operation_id: str,
        payload: dict[str, Any],
        *,
        actor: dict[str, Any],
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/"
            f"operations/{operation_id}/proof/claim",
            actor=actor,
            payload=payload,
        )

    async def process_proof(
        self,
        guild_id: int,
        ticket_id: str,
        operation_id: str,
        payload: dict[str, Any],
        *,
        actor: dict[str, Any],
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/"
            f"operations/{operation_id}/proof/process",
            actor=actor,
            payload=payload,
        )

    async def expire_operation(
        self,
        guild_id: int,
        operation_id: str,
        *,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/operations/{operation_id}/expire",
            actor=actor,
            payload={"idempotency_key": idempotency_key},
        )

    async def provisioning_error(
        self,
        guild_id: int,
        ticket_id: str,
        *,
        actor: dict[str, Any],
        error: str | None,
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/provisioning-error",
            actor=actor,
            payload={"ticket_id": ticket_id, "error": error},
        )

    async def cleanup_state(self, guild_id: int, ticket_id: str) -> dict:
        return await self._request(
            "GET",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/cleanup-state",
        )

    async def cleanup_storage(
        self,
        guild_id: int,
        ticket_id: str,
        *,
        actor: dict[str, Any],
        idempotency_key: str,
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/cleanup-storage",
            actor=actor,
            payload={"idempotency_key": idempotency_key},
        )

    async def consume_meta(
        self, guild_id: int, *, actor: dict[str, Any], limit: int = 100
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/meta-events/consume",
            actor=actor,
            payload={"limit": limit},
        )

    async def proofs(self, guild_id: int, ticket_id: str) -> list[dict]:
        return await self._request(
            "GET", f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/proofs"
        )

    async def proof_delivered(
        self,
        guild_id: int,
        ticket_id: str,
        proof_id: str,
        external_message_id: str,
        *,
        actor: dict[str, Any],
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/proofs/"
            f"{proof_id}/thread-delivered",
            actor=actor,
            payload={"external_message_id": external_message_id},
        )

    async def resource_deleted(
        self,
        guild_id: int,
        resource_id: int,
        observed_at: str,
        resource_type: str | None = None,
        *,
        actor: dict[str, Any],
    ) -> dict:
        return await self._mutation(
            "POST",
            f"/guilds/{guild_id}/modules/farm_tickets/resources/deleted",
            actor=actor,
            payload={
                "resource_id": str(resource_id),
                "resource_type": resource_type,
                "observed_at": observed_at,
            },
        )

    async def _mutation(
        self,
        method: str,
        path: str,
        *,
        actor: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict:
        return await self._request(
            method,
            path,
            json={**payload, "actor": actor},
            actor_id=actor.get("user_id") or 0,
            correlation_id=actor.get("correlation_id"),
        )

    async def action(
        self,
        guild_id: int,
        action_key: str,
        *,
        resource_id: str,
        actor: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict:
        idempotency = str(
            payload.get("idempotency_key")
            or f"{actor.get('correlation_id')}:{action_key}:{payload.get('step', 'start')}"
        )
        if action_key in {"open_ticket", "open_for_member"}:
            member_id = str(payload.get("member_id") or actor.get("user_id") or "")
            result = await self._mutation(
                "POST",
                f"/guilds/{guild_id}/modules/farm_tickets/tickets/open",
                actor=actor,
                payload={"member_id": member_id, "idempotency_key": idempotency},
            )
            return {
                "ticket": result,
                "message": "Ticket reservado. O canal privado esta sendo preparado.",
            }
        if action_key == "delete_ticket_global":
            member_id = str(payload.get("member_id") or "")
            ticket = await self.active_ticket(guild_id, member_id)
            if ticket is None:
                return {"message": "Esse membro nao possui ticket ativo."}
            result = await self._mutation(
                "POST",
                f"/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket['id']}/delete",
                actor=actor,
                payload={
                    "expected_version": ticket["revision"],
                    "idempotency_key": idempotency,
                },
            )
            return {"ticket": result, "message": "Exclusao do ticket registrada."}

        ticket = await self.ticket(guild_id, resource_id)
        if action_key in {"create_entry", "edit_entry", "withdraw"}:
            if payload.get("phase") == "save_step":
                result = await self._mutation(
                    "POST",
                    f"/guilds/{guild_id}/modules/farm_tickets/tickets/{resource_id}/"
                    f"form-drafts/{payload['draft_id']}/steps",
                    actor=actor,
                    payload={
                        "expected_version": payload["ticket_revision"],
                        "draft_revision": payload["draft_revision"],
                        "step": payload["step"],
                        "values": payload["values"],
                        "interaction_id": payload.get("interaction_id"),
                        "idempotency_key": idempotency,
                    },
                )
                if result.get("completed"):
                    message = (
                        "Recolhimento confirmado."
                        if action_key == "withdraw"
                        else "Valores salvos. Envie uma imagem valida neste canal em ate 5 minutos."
                    )
                    return {**result, "message": message}
                return {**result, "form": result["draft"]}
            kind = {
                "create_entry": "CREATE_ENTRY",
                "edit_entry": "EDIT_ENTRY",
                "withdraw": "WITHDRAWAL",
            }[action_key]
            form = await self._mutation(
                "POST",
                f"/guilds/{guild_id}/modules/farm_tickets/tickets/{resource_id}/form-drafts",
                actor=actor,
                payload={
                    "expected_version": ticket["revision"],
                    "idempotency_key": idempotency,
                    "kind": kind,
                    "target_entry_id": payload.get("target_entry_id"),
                },
            )
            return {"form": form, "ticket": ticket}
        if action_key == "list_proofs":
            proofs = await self._request(
                "GET",
                f"/guilds/{guild_id}/modules/farm_tickets/tickets/{resource_id}/proofs",
            )
            return {"proofs": proofs, "message": "Comprovantes carregados."}
        if action_key == "assign":
            result = await self._mutation(
                "POST",
                f"/guilds/{guild_id}/modules/farm_tickets/tickets/{resource_id}/assign",
                actor=actor,
                payload={
                    "expected_version": ticket["revision"],
                    "idempotency_key": idempotency,
                    "administrator_id": str(actor.get("user_id") or ""),
                },
            )
            return {"ticket": result, "message": "Ticket assumido."}
        endpoint = {"approve": "approve", "finalize": "finalize"}.get(action_key)
        if endpoint:
            result = await self._mutation(
                "POST",
                f"/guilds/{guild_id}/modules/farm_tickets/tickets/{resource_id}/{endpoint}",
                actor=actor,
                payload={
                    "expected_version": ticket["revision"],
                    "idempotency_key": idempotency,
                    "reason": payload.get("farm_ticket_reason"),
                },
            )
            return {"ticket": result, "message": "Ticket atualizado."}
        raise ValueError(f"Acao de Tickets desconhecida: {action_key}")

    farm_tickets_action = action
    farm_tickets_entries = entries
    farm_tickets_owner = owner


def module_api(platform_api: Any) -> Any:
    """Preserva doubles focados que ja implementem o contrato do modulo."""

    return (
        platform_api
        if hasattr(platform_api, "farm_tickets_action")
        else FarmTicketsAPI(platform_api)
    )
