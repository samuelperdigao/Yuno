from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit import write_audit
from app.platform.models import GuildAdminRole, GuildProfile


async def get_or_create_profile(session: AsyncSession, *, guild_id: str) -> GuildProfile:
    profile = await session.get(GuildProfile, guild_id)
    if profile is not None:
        return profile
    profile = GuildProfile(guild_id=guild_id)
    session.add(profile)
    await session.flush()
    return profile


async def read_admin_roles(session: AsyncSession, *, guild_id: str) -> list[str]:
    return list(
        (
            await session.execute(
                select(GuildAdminRole.role_id)
                .where(GuildAdminRole.guild_id == guild_id)
                .order_by(GuildAdminRole.role_id)
            )
        ).scalars()
    )


async def update_profile(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    name: str | None,
    locale: str,
    timezone_name: str,
    preferences: dict,
    correlation_id: str,
) -> GuildProfile:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=422, detail="Timezone IANA invalido.") from None
    profile = await get_or_create_profile(session, guild_id=guild_id)
    before = {
        "name": profile.name,
        "locale": profile.locale,
        "timezone": profile.timezone,
        "preferences": profile.preferences or {},
    }
    profile.name = name
    profile.locale = locale
    profile.timezone = timezone_name
    profile.preferences = preferences
    await write_audit(
        session,
        guild_id=guild_id,
        action="guild.profile_updated",
        resource_type="guild_profile",
        resource_id=guild_id,
        actor_id=actor_id,
        before=before,
        after={
            "name": name,
            "locale": locale,
            "timezone": timezone_name,
            "preferences": preferences,
        },
        correlation_id=correlation_id,
    )
    await session.commit()
    return profile


async def replace_admin_roles(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    role_ids: list[str],
    correlation_id: str,
) -> list[str]:
    normalized = sorted(set(role_ids))
    if any(not role_id.isdigit() for role_id in normalized):
        raise HTTPException(status_code=422, detail="IDs de cargo devem ser numericos.")
    before = await read_admin_roles(session, guild_id=guild_id)
    await session.execute(delete(GuildAdminRole).where(GuildAdminRole.guild_id == guild_id))
    session.add_all(
        GuildAdminRole(guild_id=guild_id, role_id=role_id, created_by=actor_id)
        for role_id in normalized
    )
    await write_audit(
        session,
        guild_id=guild_id,
        action="guild.admin_roles_replaced",
        resource_type="guild_profile",
        resource_id=guild_id,
        actor_id=actor_id,
        before={"role_ids": before},
        after={"role_ids": normalized},
        correlation_id=correlation_id,
    )
    await session.commit()
    return normalized
