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
