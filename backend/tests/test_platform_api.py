import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.api.platform import router as platform_router  # noqa: E402
from app.api.platform.deliveries import delivery_out  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db import Base, get_session  # noqa: E402
from app.models import License, LicenseStatus  # noqa: E402
from app.platform.contracts import (  # noqa: E402
    CapabilityDefinition,
    ConfigurationContract,
    ConfigurationField,
    ConfigurationFieldType,
    LifecyclePolicy,
    ModuleDefinition,
    ModuleManifest,
    PanelContract,
)
from app.platform.registry import module_registry  # noqa: E402
from app.platform.models import WorkState  # noqa: E402


def test_platform_api_revalidates_actor_and_tenant() -> None:
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
            session.add_all(
                [
                    License(key="platform-a", status=LicenseStatus.active, guild_id="guild-a"),
                    License(key="platform-b", status=LicenseStatus.active, guild_id="guild-b"),
                ]
            )
            await session.commit()
        return engine, sessions

    engine, sessions = asyncio.run(prepare())
    module_registry.register(
        ModuleDefinition(
            manifest=ModuleManifest(
                key="api_test",
                name="API Test",
                description="Contrato sintetico.",
                domain_version="1",
                runtime_modes=("domain",),
                default_runtime_mode="domain",
            ),
            configuration=ConfigurationContract(
                schema_version=1,
                fields=(
                    ConfigurationField(
                        "channel_id", "Canal", ConfigurationFieldType.channel, required=True
                    ),
                ),
            ),
            capabilities=(
                CapabilityDefinition("api_test.use", allow_resource_owner=True),
            ),
            lifecycle=LifecyclePolicy(requires_published_configuration=True),
            panels=(PanelContract("public"),),
        )
    )
    app = FastAPI()
    app.include_router(platform_router)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    token = get_settings().bot_internal_token
    headers = {"x-yuno-bot-token": token, "x-yuno-actor-id": "10"}
    actor = {
        "guild_id": "guild-a",
        "user_id": "10",
        "role_ids": [],
        "discord_permissions": ["manage_guild"],
        "actor_type": "user",
        "is_guild_owner": False,
        "correlation_id": "api-correlation",
    }
    try:
        with TestClient(app) as client:
            manifest = client.get("/internal/platform/manifest", headers=headers)
            assert manifest.status_code == 200
            modules = {item["key"]: item for item in manifest.json()["modules"]}
            assert "api_test" in modules
            assert modules["api_test"]["configuration"]["schema_version"] == 1

            draft = client.get(
                "/internal/platform/guilds/guild-a/modules/api_test/configuration/draft",
                headers=headers,
            )
            assert draft.status_code == 200
            assert draft.json()["data"] == {}

            missing_actor = client.put(
                "/internal/platform/guilds/guild-a/modules/api_test/configuration/draft",
                headers=headers,
                json={
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "schema_version": 1,
                    "data": {"channel_id": "100"},
                },
            )
            assert missing_actor.status_code == 422

            mismatched = client.put(
                "/internal/platform/guilds/guild-a/modules/api_test/configuration/draft",
                headers={**headers, "x-yuno-actor-id": "11"},
                json={
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "schema_version": 1,
                    "data": {"channel_id": "100"},
                    "actor": actor,
                },
            )
            assert mismatched.status_code == 403

            saved = client.put(
                "/internal/platform/guilds/guild-a/modules/api_test/configuration/draft",
                headers=headers,
                json={
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "schema_version": 1,
                    "data": {"channel_id": "100"},
                    "actor": actor,
                },
            )
            assert saved.status_code == 200
            published = client.post(
                "/internal/platform/guilds/guild-a/modules/api_test/configuration/publish",
                headers=headers,
                json={
                    "expected_revision": 1,
                    "expected_published_version": 0,
                    "grants": [
                        {
                            "capability": "api_test.use",
                            "subject_type": "role",
                            "subject_id": "9",
                        }
                    ],
                    "actor": actor,
                },
            )
            assert published.status_code == 200
            assert published.json()["version"] == 1

            activation = client.put(
                "/internal/platform/guilds/guild-a/modules/api_test/lifecycle",
                headers=headers,
                json={
                    "lifecycle": "active",
                    "expected_lifecycle": "inactive",
                    "actor": actor,
                },
            )
            assert activation.status_code == 200
            assert activation.json()["runtime_mode"] == "domain"

            permission = client.post(
                "/internal/platform/guilds/guild-a/modules/api_test/authorize",
                headers=headers,
                json={
                    "capability": "api_test.use",
                    "actor": {
                        "guild_id": "guild-a",
                        "user_id": "20",
                        "role_ids": ["9"],
                        "correlation_id": "permission-api",
                    },
                },
            )
            assert permission.status_code == 200 and permission.json()["allowed"]

            panel = client.post(
                "/internal/platform/guilds/guild-a/modules/api_test/panels",
                headers=headers,
                json={
                    "panel_key": "public",
                    "resource_type": "cycle",
                    "resource_id": "1",
                    "actor": actor,
                },
            )
            assert panel.status_code == 200
            cross_guild = client.patch(
                f"/internal/platform/guilds/guild-b/panels/{panel.json()['id']}",
                headers=headers,
                json={
                    "expected_render_revision": 0,
                    "state": "ready",
                    "actor": {
                        **actor,
                        "guild_id": "guild-b",
                        "correlation_id": "cross-guild",
                    },
                },
            )
            assert cross_guild.status_code == 404
    finally:
        module_registry.unregister("api_test")
        asyncio.run(engine.dispose())


def test_delivery_contract_exposes_destination_and_body_to_renderer() -> None:
    item = SimpleNamespace(
        id="delivery-1",
        guild_id="guild-a",
        module_key="registration",
        renderer_key="registration.review_request",
        destination_type="panel",
        destination_id="channel-100",
        resource_type="registration_request",
        resource_id="request-1",
        payload={"request_id": "request-1"},
        state=WorkState.claimed,
        attempts=1,
        max_attempts=10,
        correlation_id="delivery-contract",
    )

    result = delivery_out(item)

    assert result.destination_type == "panel"
    assert result.destination_id == "channel-100"
    assert result.payload == {"request_id": "request-1"}
