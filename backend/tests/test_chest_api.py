import asyncio

import app.models  # noqa: F401
from app.api.platform import router as platform_router
from app.core.config import get_settings
from app.db import Base, get_session
from app.models import License, LicenseStatus
from app.platform.registry import discover_domain_modules
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def test_chest_api_actor_revision_idempotency_and_capabilities():
    async def prepare():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            session.add(
                License(key="chest-api", status=LicenseStatus.active, guild_id="100")
            )
            await session.commit()
        return engine, sessions

    discover_domain_modules()
    engine, sessions = asyncio.run(prepare())
    app = FastAPI()
    app.include_router(platform_router)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    token = get_settings().bot_internal_token
    headers = {
        "x-yuno-bot-token": token,
        "x-yuno-actor-id": "900",
        "x-yuno-correlation-id": "api-chest",
    }
    actor = {
        "guild_id": "100",
        "user_id": "900",
        "role_ids": [],
        "discord_permissions": ["administrator"],
        "actor_type": "user",
        "is_guild_owner": False,
        "correlation_id": "api-chest",
    }
    try:
        with TestClient(app) as client:
            draft = client.post(
                "/internal/platform/guilds/100/modules/chest/catalog/draft",
                headers=headers,
                json={"actor": actor},
            )
            assert draft.status_code == 200
            assert draft.json()["revision"] == 0

            mismatched = client.put(
                "/internal/platform/guilds/100/modules/chest/catalog/draft/chests",
                headers=headers,
                json={
                    "name": "Bau",
                    "active": True,
                    "position": 0,
                    "expected_revision": 0,
                    "idempotency_key": "bad-actor",
                    "actor": {**actor, "guild_id": "200"},
                },
            )
            assert mismatched.status_code == 403

            settings = client.put(
                "/internal/platform/guilds/100/modules/chest/configuration/draft",
                headers=headers,
                json={
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "schema_version": 1,
                    "idempotency_key": "settings",
                    "data": {
                        "panel_channel_id": "10",
                        "log_channel_id": "20",
                        "show_balances_to_members": True,
                        "allow_personal_history": True,
                        "withdrawal_reason_required": True,
                        "operator_role_ids": [],
                        "panel_title": "Sistema de Bau",
                        "panel_description": "Painel de estoque.",
                    },
                    "actor": actor,
                },
            )
            assert settings.status_code == 200
            assert settings.json()["revision"] == 1

            chest_payload = {
                "name": "Central",
                "active": True,
                "position": 0,
                "expected_revision": 1,
                "idempotency_key": "chest",
                "actor": actor,
            }
            chest = client.put(
                "/internal/platform/guilds/100/modules/chest/catalog/draft/chests",
                headers=headers,
                json=chest_payload,
            )
            replay = client.put(
                "/internal/platform/guilds/100/modules/chest/catalog/draft/chests",
                headers=headers,
                json={**chest_payload, "expected_revision": 0, "name": "Ignorado"},
            )
            assert chest.status_code == replay.status_code == 200
            assert chest.json()["id"] == replay.json()["id"]

            stale = client.put(
                "/internal/platform/guilds/100/modules/chest/catalog/draft/items",
                headers=headers,
                json={
                    "name": "Item",
                    "unit": "un",
                    "active": True,
                    "position": 0,
                    "expected_revision": 1,
                    "idempotency_key": "stale",
                    "actor": actor,
                },
            )
            assert stale.status_code == 409
            assert stale.json()["detail"]["current_revision"] == 2
    finally:
        asyncio.run(engine.dispose())
