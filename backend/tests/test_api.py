import os
import sys
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
