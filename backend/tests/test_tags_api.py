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


def test_tags_api_enforces_actor_guild_snapshot_and_revisions() -> None:
    discover_domain_modules()

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
                    License(key="tags-a", status=LicenseStatus.active, guild_id="100"),
                    License(key="tags-b", status=LicenseStatus.active, guild_id="101"),
                ]
            )
            await session.commit()
        return engine, sessions

    engine, sessions = asyncio.run(prepare())
    app = FastAPI()
    app.include_router(platform_router)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    headers = {
        "x-yuno-bot-token": get_settings().bot_internal_token,
        "x-yuno-actor-id": "10",
        "x-yuno-correlation-id": "tags-api",
    }
    actor = {
        "guild_id": "100",
        "user_id": "10",
        "role_ids": [],
        "discord_permissions": ["manage_guild"],
        "actor_type": "user",
        "is_guild_owner": False,
        "correlation_id": "tags-api",
    }
    try:
        with TestClient(app) as client:
            draft = client.get(
                "/internal/platform/guilds/100/modules/tags/bindings/draft", headers=headers
            )
            assert draft.status_code == 200
            assert draft.json()["bindings"] == []

            invalid_role = client.put(
                "/internal/platform/guilds/100/modules/tags/bindings/draft",
                headers=headers,
                json={
                    "discord_role_id": "11",
                    "guild_role_ids": ["100", "10"],
                    "tag": "[X]",
                    "enabled": True,
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "actor": actor,
                },
            )
            assert invalid_role.status_code == 422

            saved = client.put(
                "/internal/platform/guilds/100/modules/tags/bindings/draft",
                headers=headers,
                json={
                    "discord_role_id": "10",
                    "guild_role_ids": ["100", "10", "90"],
                    "tag": "[MEM]",
                    "enabled": True,
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "actor": actor,
                },
            )
            assert saved.status_code == 200
            assert saved.json()["revision"] == 1

            stale = client.put(
                "/internal/platform/guilds/100/modules/tags/bindings/draft",
                headers=headers,
                json={
                    "discord_role_id": "10",
                    "guild_role_ids": ["100", "10", "90"],
                    "tag": "[NOVO]",
                    "enabled": True,
                    "expected_revision": 0,
                    "expected_published_version": 0,
                    "actor": actor,
                },
            )
            assert stale.status_code == 409

            wrong_actor = client.put(
                "/internal/platform/guilds/100/modules/tags/bindings/draft",
                headers=headers,
                json={
                    "discord_role_id": "10",
                    "guild_role_ids": ["100", "10"],
                    "tag": "[X]",
                    "enabled": True,
                    "expected_revision": 1,
                    "expected_published_version": 0,
                    "actor": {**actor, "guild_id": "101"},
                },
            )
            assert wrong_actor.status_code == 403

            published = client.post(
                "/internal/platform/guilds/100/modules/tags/configuration/publish",
                headers=headers,
                json={
                    "expected_revision": 1,
                    "expected_published_version": 0,
                    "grants": [],
                    "actor": actor,
                },
            )
            assert published.status_code == 200
            effective = client.get(
                "/internal/platform/guilds/100/modules/tags/bindings/effective", headers=headers
            )
            assert effective.status_code == 200
            assert effective.json()["bindings"][0]["tag"] == "[MEM]"

            tampered_snapshot = client.post(
                "/internal/platform/guilds/100/modules/tags/preview",
                headers=headers,
                json={
                    "snapshot": {
                        "guild_id": "101",
                        "discord_user_id": "200",
                        "member_found": True,
                        "role_ids": ["10"],
                        "hierarchy_role_ids": ["100", "10", "90"],
                        "current_nickname": "Mineiro | 6627",
                    },
                    "source": "effective",
                    "base_only": False,
                    "actor": actor,
                },
            )
            assert tampered_snapshot.status_code == 403

            diagnostics = client.get(
                "/internal/platform/guilds/100/modules/tags/operational-diagnostics",
                headers=headers,
            )
            assert diagnostics.status_code == 200
            assert diagnostics.json()["binding_count"] == 1
    finally:
        asyncio.run(engine.dispose())
