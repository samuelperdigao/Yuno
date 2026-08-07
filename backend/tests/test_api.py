import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-yuno.db"
os.environ["ADMIN_TOKEN"] = "admin-test"
os.environ["BOT_INTERNAL_TOKEN"] = "bot-test"
os.environ["MERCADO_PAGO_WEBHOOK_SECRET"] = "webhook-test"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

db_file = Path("test-yuno.db")
if db_file.exists():
    db_file.unlink()

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_payment_license_activation_and_validation(client: TestClient) -> None:
    payment = client.post(
        "/webhooks/mercadopago",
        headers={"x-yuno-webhook-secret": "webhook-test"},
        json={"id": "pay-1", "status": "approved"},
    )
    assert payment.status_code == 200
    license_key = payment.json()["license_key"]

    activation = client.post(
        "/licenses/activate",
        json={
            "license_key": license_key,
            "guild_id": "123",
            "guild_name": "Cidade Teste",
            "owner_discord_id": "999",
        },
    )
    assert activation.status_code == 200
    assert activation.json()["status"] == "active"

    validation = client.post(
        "/internal/licenses/validate",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"guild_id": "123"},
    )
    assert validation.status_code == 200
    assert validation.json()["allowed"] is True


def test_admin_can_issue_list_and_activate_manual_license(client: TestClient) -> None:
    denied = client.post("/licenses/issue", json={"reference": "sale-denied"})
    assert denied.status_code == 401

    issued = client.post(
        "/licenses/issue",
        headers={"x-yuno-admin-token": "admin-test"},
        json={
            "reference": "sale-manual-1",
            "customer_name": "Cliente Teste",
            "customer_email": "CLIENTE@example.com",
            "customer_discord_user_id": "456",
        },
    )
    assert issued.status_code == 200
    assert issued.json()["status"] == "pending"
    assert issued.json()["payment_provider"] == "manual"

    duplicate = client.post(
        "/licenses/issue",
        headers={"x-yuno-admin-token": "admin-test"},
        json={"reference": "sale-manual-1"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/licenses", headers={"x-yuno-admin-token": "admin-test"})
    assert listed.status_code == 200
    assert issued.json()["key"] in {item["key"] for item in listed.json()}

    activation = client.post(
        "/licenses/activate",
        json={
            "license_key": issued.json()["key"],
            "guild_id": "manual-guild",
            "guild_name": "Cidade Manual",
            "owner_discord_id": "456",
        },
    )
    assert activation.status_code == 200
    assert activation.json()["status"] == "active"


def test_mercado_pago_webhook_fails_closed_without_secret(client: TestClient) -> None:
    settings = get_settings()
    original = settings.mercado_pago_webhook_secret
    settings.mercado_pago_webhook_secret = ""
    try:
        response = client.post("/webhooks/mercadopago", json={"id": "pay-open", "status": "approved"})
    finally:
        settings.mercado_pago_webhook_secret = original
    assert response.status_code == 503


def test_permission_blocks_unlicensed_guild(client: TestClient) -> None:
    response = client.post(
        "/internal/permissions/check",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "guild_id": "missing",
            "module": "set",
            "command": "solicitar",
            "user_role_ids": [],
        },
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False


def test_bot_can_save_setup_config_and_permissions_use_channels(client: TestClient) -> None:
    payment = client.post(
        "/webhooks/mercadopago",
        headers={"x-yuno-webhook-secret": "webhook-test"},
        json={"id": "pay-setup", "status": "approved"},
    )
    assert payment.status_code == 200

    activation = client.post(
        "/licenses/activate",
        json={
            "license_key": payment.json()["license_key"],
            "guild_id": "setup-guild",
            "guild_name": "Cidade Setup",
            "owner_discord_id": "999",
        },
    )
    assert activation.status_code == 200

    config = client.put(
        "/internal/guilds/setup-guild/config",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "guild_name": "Cidade Setup",
            "admin_role_ids": ["admin-role"],
            "log_channel_id": "logs",
            "modules": {"set": True, "meta": True},
            "command_permissions": {"set.solicitar": {"channel_ids": ["set-channel"]}},
            "messages": {},
            "settings": {"discord_setup": {"channel_ids": {"set_solicitar": "set-channel"}}},
        },
    )
    assert config.status_code == 200
    assert config.json()["log_channel_id"] == "logs"

    blocked = client.post(
        "/internal/permissions/check",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "guild_id": "setup-guild",
            "module": "set",
            "command": "solicitar",
            "user_role_ids": [],
            "channel_id": "wrong-channel",
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["allowed"] is False

    allowed = client.post(
        "/internal/permissions/check",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "guild_id": "setup-guild",
            "module": "set",
            "command": "solicitar",
            "user_role_ids": [],
            "channel_id": "set-channel",
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True


def activate_test_guild(client: TestClient, guild_id: str) -> None:
    payment = client.post(
        "/webhooks/mercadopago",
        headers={"x-yuno-webhook-secret": "webhook-test"},
        json={"id": f"pay-{guild_id}", "status": "approved"},
    )
    assert payment.status_code == 200
    activation = client.post(
        "/licenses/activate",
        json={
            "license_key": payment.json()["license_key"],
            "guild_id": guild_id,
            "guild_name": f"Guild {guild_id}",
            "owner_discord_id": "999",
        },
    )
    assert activation.status_code == 200


def test_internal_ausencias_upsert_list_message_and_notice(client: TestClient) -> None:
    activate_test_guild(client, "ausencia-a")
    now = datetime.now(timezone.utc)

    created = client.post(
        "/internal/guilds/ausencia-a/ausencias",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "user_id": "42",
            "nome": "Ana",
            "dias": 3,
            "motivo": "Viagem",
            "inicio": now.isoformat(),
            "fim": (now + timedelta(days=3)).isoformat(),
        },
    )
    assert created.status_code == 200
    assert created.json()["motivo"] == "Viagem"
    assert created.json()["avisado"] == 0

    replaced = client.post(
        "/internal/guilds/ausencia-a/ausencias",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "user_id": "42",
            "nome": "Ana Atualizada",
            "dias": 5,
            "motivo": "Trabalho",
            "inicio": now.isoformat(),
            "fim": (now + timedelta(days=5)).isoformat(),
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["nome"] == "Ana Atualizada"
    assert replaced.json()["dias"] == 5

    active = client.get(
        "/internal/guilds/ausencia-a/ausencias",
        headers={"x-yuno-bot-token": "bot-test"},
        params={"active_only": True},
    )
    assert active.status_code == 200
    assert [item["user_id"] for item in active.json()] == ["42"]

    message = client.patch(
        "/internal/guilds/ausencia-a/ausencias/42/message",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"message_id": "999"},
    )
    assert message.status_code == 200
    assert message.json()["message_id"] == "999"

    expired = client.post(
        "/internal/guilds/ausencia-a/ausencias",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "user_id": "43",
            "nome": "Bruno",
            "dias": 1,
            "motivo": "Não informado",
            "inicio": (now - timedelta(days=2)).isoformat(),
            "fim": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert expired.status_code == 200

    pending = client.get(
        "/internal/guilds/ausencia-a/ausencias",
        headers={"x-yuno-bot-token": "bot-test"},
        params={"pending_notice_only": True},
    )
    assert pending.status_code == 200
    assert [item["user_id"] for item in pending.json()] == ["43"]

    marked = client.patch("/internal/guilds/ausencia-a/ausencias/43/avisado", headers={"x-yuno-bot-token": "bot-test"})
    assert marked.status_code == 200
    assert marked.json()["avisado"] == 1

    pending_after = client.get(
        "/internal/guilds/ausencia-a/ausencias",
        headers={"x-yuno-bot-token": "bot-test"},
        params={"pending_notice_only": True},
    )
    assert pending_after.status_code == 200
    assert pending_after.json() == []


def test_farm_ticket_config_goal_ticket_progress_and_finalize(client: TestClient) -> None:
    activate_test_guild(client, "farm-a")
    activate_test_guild(client, "farm-b")

    config_a = client.put(
        "/internal/farm-tickets/guilds/farm-a/config",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "category_ids": ["10", "11"],
            "admin_role_ids": ["20"],
            "log_channel_id": "30",
            "panel_channel_id": "40",
            "folders_category_id": None,
            "participant_role_ids": [],
        },
    )
    assert config_a.status_code == 200

    config_b = client.put(
        "/internal/farm-tickets/guilds/farm-b/config",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "category_ids": ["99"],
            "admin_role_ids": ["88"],
            "log_channel_id": "77",
            "panel_channel_id": "66",
            "folders_category_id": None,
            "participant_role_ids": [],
        },
    )
    assert config_b.status_code == 200
    read_a = client.get("/internal/farm-tickets/guilds/farm-a/config", headers={"x-yuno-bot-token": "bot-test"})
    assert read_a.json()["category_ids"] == ["10", "11"]

    goal = client.put(
        "/internal/farm-tickets/guilds/farm-a/goals",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"week_id": "2026-W30", "items": [{"name": "Item", "quantity": 10}], "created_by": "999"},
    )
    assert goal.status_code == 200

    reserve = client.post(
        "/internal/farm-tickets/guilds/farm-a/tickets/reserve",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"week_id": "2026-W30", "user_id": "42", "member_name": "Ana"},
    )
    assert reserve.status_code == 200
    assert reserve.json()["existing"] is False
    ticket_id = reserve.json()["ticket"]["id"]

    duplicate = client.post(
        "/internal/farm-tickets/guilds/farm-a/tickets/reserve",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"week_id": "2026-W30", "user_id": "42", "member_name": "Ana"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["existing"] is True
    assert duplicate.json()["ticket"]["id"] == ticket_id

    entry = client.post(
        f"/internal/farm-tickets/tickets/{ticket_id}/entries",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "actor_id": "42",
            "values": {"Item": 5},
            "proof_channel_id": "50",
            "proof_message_id": "60",
            "proof_url": "https://example.com/proof.png",
            "observacao": "ok",
        },
    )
    assert entry.status_code == 200
    assert entry.json()["progress"]["items"]["Item"]["delivered"] == 5
    assert entry.json()["progress"]["percent"] == 50

    ranking = client.get(
        "/internal/farm-tickets/guilds/farm-a/ranking/2026-W30",
        headers={"x-yuno-bot-token": "bot-test"},
    )
    assert ranking.status_code == 200
    assert ranking.json()["participants"] == 1
    assert ranking.json()["ranking"] == [
        {
            "position": 1,
            "user_id": "42",
            "member_name": "Ana",
            "delivered_total": 5,
            "completion_percent": 50,
            "entry_count": 1,
            "items": {"Item": 5},
        }
    ]

    finalize = client.post(
        f"/internal/farm-tickets/tickets/{ticket_id}/finalize",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"actor_id": "20", "reason": "fim"},
    )
    assert finalize.status_code == 200
    assert finalize.json()["status"] == "aprovado_parcial"

    new_ticket_same_week = client.post(
        "/internal/farm-tickets/guilds/farm-a/tickets/reserve",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"week_id": "2026-W30", "user_id": "42", "member_name": "Ana"},
    )
    assert new_ticket_same_week.status_code == 200
    assert new_ticket_same_week.json()["existing"] is False


def test_farm_ticket_admin_actions_and_log_queue(client: TestClient) -> None:
    activate_test_guild(client, "farm-log")
    client.put(
        "/internal/farm-tickets/guilds/farm-log/config",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "category_ids": ["10"],
            "admin_role_ids": ["20"],
            "log_channel_id": "30",
            "panel_channel_id": "40",
            "folders_category_id": None,
            "participant_role_ids": [],
        },
    )
    client.put(
        "/internal/farm-tickets/guilds/farm-log/goals",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"week_id": "2026-W30", "items": [{"name": "Item", "quantity": 10}], "created_by": "999"},
    )
    ticket_id = client.post(
        "/internal/farm-tickets/guilds/farm-log/tickets/reserve",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"week_id": "2026-W30", "user_id": "42", "member_name": "Ana"},
    ).json()["ticket"]["id"]

    assigned = client.post(
        f"/internal/farm-tickets/tickets/{ticket_id}/assign",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"actor_id": "20"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == "20"

    pending = client.get("/internal/farm-tickets/actions/pending-logs", headers={"x-yuno-bot-token": "bot-test"})
    assert pending.status_code == 200
    assert pending.json()
    action_id = pending.json()[0]["id"]
    sent = client.post(
        f"/internal/farm-tickets/actions/{action_id}/log-sent",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"log_message_id": "123"},
    )
    assert sent.status_code == 200
    assert sent.json()["log_message_id"] == "123"


def test_parceria_requires_active_license(client: TestClient) -> None:
    response = client.get(
        "/internal/parcerias/guilds/no-license/config",
        headers={"x-yuno-bot-token": "bot-test"},
    )
    assert response.status_code == 403


def test_parceria_config_registration_edit_and_lifecycle(client: TestClient) -> None:
    activate_test_guild(client, "parceria-a")

    config = client.put(
        "/internal/parcerias/guilds/parceria-a/config",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "category_id": "10",
            "registrar_channel_id": "11",
            "ativas_channel_id": "12",
            "panel_message_id": None,
        },
    )
    assert config.status_code == 200
    assert config.json()["ativas_channel_id"] == "12"

    read_config = client.get("/internal/parcerias/guilds/parceria-a/config", headers={"x-yuno-bot-token": "bot-test"})
    assert read_config.status_code == 200
    assert read_config.json()["registrar_channel_id"] == "11"

    created = client.post(
        "/internal/parcerias/guilds/parceria-a",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "nome_familia": "Comando Vermelho",
            "produto": "Armamento",
            "contato_01": "João",
            "contato_02": None,
            "mensagem_lista_id": "999",
            "nome_arquivo_imagem": "uniforme_comando-vermelho.png",
            "registrado_por": "42",
        },
    )
    assert created.status_code == 200
    parceria_id = created.json()["id"]
    assert created.json()["mensagem_lista_id"] == "999"

    duplicate = client.post(
        "/internal/parcerias/guilds/parceria-a",
        headers={"x-yuno-bot-token": "bot-test"},
        json={
            "nome_familia": "COMANDO VERMELHO",
            "produto": "Munição",
            "contato_01": None,
            "contato_02": None,
            "mensagem_lista_id": "1000",
            "nome_arquivo_imagem": "uniforme_comando-vermelho.png",
            "registrado_por": "43",
        },
    )
    assert duplicate.status_code == 409

    found = client.get(
        "/internal/parcerias/guilds/parceria-a/by-name",
        headers={"x-yuno-bot-token": "bot-test"},
        params={"nome_familia": "comando vermelho"},
    )
    assert found.status_code == 200
    assert found.json()["id"] == parceria_id

    exists = client.get(
        "/internal/parcerias/guilds/parceria-a/name-exists",
        headers={"x-yuno-bot-token": "bot-test"},
        params={"nome_familia": "Comando Vermelho", "exclude_id": parceria_id},
    )
    assert exists.status_code == 200
    assert exists.json()["exists"] is False

    updated = client.patch(
        f"/internal/parcerias/{parceria_id}",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"nome_familia": "Comando Azul", "produto": "Veículos", "contato_01": None, "contato_02": "Pedro"},
    )
    assert updated.status_code == 200
    assert updated.json()["nome_familia"] == "Comando Azul"
    assert updated.json()["mensagem_lista_id"] == "999"

    with_image = client.patch(
        f"/internal/parcerias/{parceria_id}/imagem",
        headers={"x-yuno-bot-token": "bot-test"},
        json={"nome_arquivo_imagem": "uniforme_comando-azul.webp"},
    )
    assert with_image.status_code == 200
    assert with_image.json()["nome_arquivo_imagem"] == "uniforme_comando-azul.webp"

    active = client.get("/internal/parcerias/guilds/parceria-a/active", headers={"x-yuno-bot-token": "bot-test"})
    assert active.status_code == 200
    assert len(active.json()) == 1

    deactivated = client.post(f"/internal/parcerias/{parceria_id}/desativar", headers={"x-yuno-bot-token": "bot-test"})
    assert deactivated.status_code == 200

    active_after = client.get("/internal/parcerias/guilds/parceria-a/active", headers={"x-yuno-bot-token": "bot-test"})
    assert active_after.json() == []

    missing = client.get(f"/internal/parcerias/{parceria_id + 9999}", headers={"x-yuno-bot-token": "bot-test"})
    assert missing.status_code == 200
    assert missing.json() is None


def test_control_plane_draft_publish_conflict_projection_and_audit(client: TestClient) -> None:
    activate_test_guild(client, "cp-guild-a")
    activate_test_guild(client, "cp-guild-b")
    base_headers = {"x-yuno-bot-token": "bot-test", "x-yuno-actor-id": "1001"}
    state_url = "/internal/control-plane/guilds/cp-guild-a/modules/meta"

    assert client.get(state_url).status_code == 401
    assert client.get(state_url, headers={"x-yuno-bot-token": "bot-test"}).status_code == 422
    assert client.get(
        "/internal/control-plane/guilds/missing/modules/meta", headers=base_headers
    ).status_code == 403

    initial = client.get(state_url, headers=base_headers)
    assert initial.status_code == 200
    assert initial.json()["draft_revision"] == 0
    assert initial.json()["published_revision"] == 0

    unsupported = client.put(
        f"{state_url}/draft",
        headers=base_headers,
        json={"expected_revision": 0, "schema_version": 2, "draft_data": {}},
    )
    assert unsupported.status_code == 422

    existing_config = client.put(
        "/internal/guilds/cp-guild-a/config",
        headers=base_headers,
        json={
            "guild_name": "Control Plane A",
            "modules": {"meta": True, "ticket": False},
            "command_permissions": {"ticket.abrir": {"role_ids": ["ticket-role"]}},
            "messages": {"ticket": {"panel": {"title": "Tickets"}}},
            "settings": {"ticket": {"panel_channel_id": "900"}, "discord_setup": {"x": 1}},
        },
    )
    assert existing_config.status_code == 200

    draft_data = {
        "panel_channel_id": "101",
        "result_channel_id": "102",
        "allowed_role_id": "103",
        "default_items": [{"name": "Kit Desmanche", "quantity": 50}],
        "panel": {"title": "Metas Semanais", "description": "Defina suas metas.", "color": "#FFC72C"},
    }
    saved = client.put(
        f"{state_url}/draft",
        headers=base_headers,
        json={"expected_revision": 0, "schema_version": 1, "draft_data": draft_data},
    )
    assert saved.status_code == 200
    assert saved.json()["draft_revision"] == 1
    assert saved.json()["published_data"] == {}

    runtime_before = client.get(
        "/internal/guilds/cp-guild-a/config", headers={"x-yuno-bot-token": "bot-test"}
    ).json()
    assert "meta" not in runtime_before["settings"]

    conflict = client.put(
        f"{state_url}/draft",
        headers=base_headers,
        json={"expected_revision": 0, "schema_version": 1, "draft_data": draft_data},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current_revision"] == 1

    isolated = client.get(
        "/internal/control-plane/guilds/cp-guild-b/modules/meta",
        headers={**base_headers, "x-yuno-actor-id": "1002"},
    )
    assert isolated.status_code == 200
    assert isolated.json()["draft_revision"] == 0

    published = client.post(
        f"{state_url}/publish",
        headers=base_headers,
        json={
            "expected_revision": 1,
            "schema_version": 1,
            "projection": {
                "settings": {
                    "panel_channel_id": "101",
                    "result_channel_id": "102",
                    "allowed_role_id": "103",
                    "panel_message_id": "104",
                    "default_items": draft_data["default_items"],
                },
                "messages": draft_data["panel"],
                "command_permissions": {
                    "meta.definir": {"channel_ids": ["101"], "role_ids": ["103"]}
                },
                "enabled": True,
            },
            "panel_refs": {"panel_channel_id": "101", "panel_message_id": "104"},
        },
    )
    assert published.status_code == 200
    assert published.json()["published_revision"] == 1
    assert published.json()["published_data"] == draft_data

    runtime_after = client.get(
        "/internal/guilds/cp-guild-a/config", headers={"x-yuno-bot-token": "bot-test"}
    ).json()
    assert runtime_after["settings"]["meta"]["panel_message_id"] == "104"
    assert runtime_after["settings"]["ticket"]["panel_channel_id"] == "900"
    assert runtime_after["settings"]["discord_setup"] == {"x": 1}
    assert runtime_after["messages"]["ticket"]["panel"]["title"] == "Tickets"
    assert runtime_after["command_permissions"]["ticket.abrir"]["role_ids"] == ["ticket-role"]
    assert runtime_after["modules"]["ticket"] is False

    import asyncio
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import AuditLog

    async def read_audit() -> list[AuditLog]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(AuditLog).where(
                    AuditLog.guild_id == "cp-guild-a",
                    AuditLog.action == "control_plane.published",
                )
            )
            return list(result.scalars())

    logs = asyncio.run(read_audit())
    assert len(logs) == 1
    assert logs[0].actor_id == "1001"
    assert logs[0].payload["snapshot"] == draft_data
