import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.farm_tickets.definition import (  # noqa: E402
    ADMIN_CAPABILITIES,
    _validate_permission_grants,
)
from app.platform.permissions import authorize  # noqa: E402
from app.platform.registry import discover_domain_modules  # noqa: E402
from app.platform.schemas import ActorContextIn  # noqa: E402


def _actor(**changes) -> ActorContextIn:
    payload = {
        "guild_id": "guild-a",
        "user_id": "100",
        "role_ids": [],
        "discord_permissions": [],
        "actor_type": "user",
        "is_guild_owner": False,
        "correlation_id": "tickets-permission",
    }
    payload.update(changes)
    return ActorContextIn(**payload)


def test_ticket_operations_distinguish_owner_discord_admin_and_manage_guild() -> None:
    async def scenario() -> None:
        discover_domain_modules()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session:
                owner = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="farm_tickets",
                    capability_key="farm_tickets.withdraw",
                    actor=_actor(is_guild_owner=True),
                    resource_id="ticket-a",
                )
                administrator = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="farm_tickets",
                    capability_key="farm_tickets.approve",
                    actor=_actor(discord_permissions=["administrator"]),
                    resource_id="ticket-a",
                )
                central_only = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="farm_tickets",
                    capability_key="farm_tickets.approve",
                    actor=_actor(discord_permissions=["manage_guild"]),
                    resource_id="ticket-a",
                )
                central_configuration = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="farm_tickets",
                    capability_key="farm_tickets.configure",
                    actor=_actor(discord_permissions=["manage_guild"]),
                )
                resource_owner = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="farm_tickets",
                    capability_key="farm_tickets.submit",
                    actor=_actor(resource_owner_id="100"),
                    resource_id="ticket-a",
                )
                assert owner.allowed
                assert administrator.allowed
                assert not central_only.allowed
                assert central_configuration.allowed
                assert resource_owner.allowed
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_published_ticket_admin_roles_must_move_all_operational_grants_together() -> (
    None
):
    def grant(capability: str, role_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            capability=capability,
            subject_type="role",
            subject_id=role_id,
            scope_type="guild",
            scope_id="",
        )

    open_own = SimpleNamespace(
        capability="farm_tickets.open_own",
        subject_type="everyone",
        subject_id="",
        scope_type="guild",
        scope_id="",
    )
    old_grants = [
        open_own,
        *(grant(capability, "10") for capability in ADMIN_CAPABILITIES),
    ]
    assert (
        _validate_permission_grants({"administrator_role_ids": ["10"]}, old_grants)
        == []
    )
    assert _validate_permission_grants({"administrator_role_ids": ["20"]}, old_grants)
    new_grants = [
        open_own,
        *(grant(capability, "20") for capability in ADMIN_CAPABILITIES),
    ]
    assert (
        _validate_permission_grants({"administrator_role_ids": ["20"]}, new_grants)
        == []
    )
