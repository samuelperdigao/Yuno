import asyncio
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.api.platform import router as platform_router  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db import Base, get_session  # noqa: E402
from app.models import License, LicenseStatus  # noqa: E402
from app.platform.registry import discover_domain_modules  # noqa: E402


def test_registration_api_enforces_grants_tenant_and_phased_approval() -> None:
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
                    License(key="registration-a", status=LicenseStatus.active, guild_id="guild-a"),
                    License(key="registration-b", status=LicenseStatus.active, guild_id="guild-b"),
                ]
            )
            await session.commit()
        return engine, sessions

    engine, sessions = asyncio.run(prepare())
    discover_domain_modules()
    app = FastAPI()
    app.include_router(platform_router)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    token = get_settings().bot_internal_token
    base_headers = {"x-yuno-bot-token": token}

    def actor(
        user_id: str,
        *,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        correlation: str,
    ) -> dict:
        return {
            "guild_id": "guild-a",
            "user_id": user_id,
            "role_ids": roles or [],
            "discord_permissions": permissions or [],
            "actor_type": "user",
            "is_guild_owner": False,
            "correlation_id": correlation,
        }

    try:
        with TestClient(app) as client:
            admin = actor("900", permissions=["manage_guild"], correlation="config")
            admin_headers = {**base_headers, "x-yuno-actor-id": "900"}
            draft = client.get(
                "/internal/platform/guilds/guild-a/modules/registration/configuration/draft",
                headers=admin_headers,
            )
            assert draft.status_code == 200
            config = {
                **draft.json()["data"],
                "panel_channel_id": "1001",
                "approval_channel_id": "1002",
                "log_channel_id": "1003",
                "member_role_id": "1004",
                "approver_role_ids": ["9"],
            }
            saved = client.put(
                "/internal/platform/guilds/guild-a/modules/registration/configuration/draft",
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "schema_version": 1,
                    "data": config,
                    "actor": admin,
                },
            )
            assert saved.status_code == 200
            invalid_permissions = client.post(
                "/internal/platform/guilds/guild-a/modules/registration/configuration/publish",
                headers=admin_headers,
                json={
                    "expected_revision": 1,
                    "expected_published_version": 0,
                    "grants": [
                        {
                            "capability": "registration.review",
                            "subject_type": "role",
                            "subject_id": "9",
                        }
                    ],
                    "actor": admin,
                },
            )
            assert invalid_permissions.status_code == 422
            published = client.post(
                "/internal/platform/guilds/guild-a/modules/registration/configuration/publish",
                headers=admin_headers,
                json={
                    "expected_revision": 1,
                    "expected_published_version": 0,
                    "grants": [
                        {
                            "capability": "registration.submit",
                            "subject_type": "everyone",
                        },
                        {
                            "capability": "registration.review",
                            "subject_type": "role",
                            "subject_id": "9",
                        },
                    ],
                    "actor": admin,
                },
            )
            assert published.status_code == 200
            activation = client.put(
                "/internal/platform/guilds/guild-a/modules/registration/lifecycle",
                headers=admin_headers,
                json={
                    "lifecycle": "active",
                    "expected_lifecycle": "inactive",
                    "actor": admin,
                },
            )
            assert activation.status_code == 200

            submit_actor = actor("10", correlation="submit")
            submitted = client.post(
                "/internal/platform/guilds/guild-a/modules/registration/requests",
                headers={**base_headers, "x-yuno-actor-id": "10"},
                json={
                    "actor": submit_actor,
                    "registration": {"name": "Ana", "player_id": "001"},
                    "panel_config_version": 1,
                },
            )
            assert submitted.status_code == 200
            request_id = submitted.json()["id"]

            manager = actor("20", permissions=["manage_guild"], correlation="manager")
            denied = client.post(
                f"/internal/platform/guilds/guild-a/modules/registration/requests/{request_id}/approval/claim",
                headers={**base_headers, "x-yuno-actor-id": "20"},
                json={"actor": manager},
            )
            assert denied.status_code == 403

            reviewer = actor("21", roles=["9"], correlation="review")
            reviewer_headers = {**base_headers, "x-yuno-actor-id": "21"}
            claim = client.post(
                f"/internal/platform/guilds/guild-a/modules/registration/requests/{request_id}/approval/claim",
                headers=reviewer_headers,
                json={"actor": reviewer},
            )
            assert claim.status_code == 200
            token_value = claim.json()["operation_token"]
            assert claim.json()["target_nickname"] == "Ana | 001"
            retry_claim = client.post(
                f"/internal/platform/guilds/guild-a/modules/registration/requests/{request_id}/approval/claim",
                headers=reviewer_headers,
                json={"actor": reviewer, "operation_token": token_value},
            )
            assert retry_claim.status_code == 200

            preflight = client.post(
                f"/internal/platform/guilds/guild-a/modules/registration/requests/{request_id}/approval/preflight",
                headers=reviewer_headers,
                json={
                    "actor": reviewer,
                    "operation_token": token_value,
                    "previous_nickname": "Antes",
                    "role_was_present": False,
                    "target_nickname": "Ana | 001",
                },
            )
            assert preflight.status_code == 200
            for step in ("nickname", "role"):
                response = client.post(
                    f"/internal/platform/guilds/guild-a/modules/registration/requests/{request_id}/approval/step",
                    headers=reviewer_headers,
                    json={"actor": reviewer, "operation_token": token_value, "step": step},
                )
                assert response.status_code == 200
            completed = client.post(
                f"/internal/platform/guilds/guild-a/modules/registration/requests/{request_id}/approval/complete",
                headers=reviewer_headers,
                json={"actor": reviewer, "operation_token": token_value},
            )
            assert completed.status_code == 200
            assert completed.json()["request"]["status"] == "approved"

            cross_tenant = client.get(
                f"/internal/platform/guilds/guild-b/modules/registration/requests/{request_id}",
                headers=base_headers,
            )
            assert cross_tenant.status_code == 404

            audit = client.get(
                "/internal/platform/guilds/guild-a/audit",
                headers=base_headers,
                params={"module_key": "registration"},
            )
            assert audit.status_code == 200
            actions = {item["action"] for item in audit.json()}
            assert {
                "registration.config_updated",
                "registration.config_published",
                "registration.request_submitted",
                "registration.request_approved",
            } <= actions
    finally:
        asyncio.run(engine.dispose())
