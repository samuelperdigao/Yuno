from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.registration.domain import OrganizationMemberStatus, render_nickname
from app.domain_modules.registration.models import OrganizationMember
from app.domain_modules.registration.schemas import RegistrationConfig
from app.platform.models import ModuleConfigVersion, ModuleInstance


@dataclass(frozen=True)
class BaseMemberIdentity:
    identity_id: str
    guild_id: str
    discord_user_id: str
    status: OrganizationMemberStatus
    base_nickname: str
    config_version: int
    fingerprint: str


async def read_base_member_identity(
    session: AsyncSession, *, guild_id: str, discord_user_id: str
) -> BaseMemberIdentity | None:
    member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.guild_id == guild_id,
                OrganizationMember.discord_user_id == discord_user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        return None
    instance = (
        await session.execute(
            select(ModuleInstance).where(
                ModuleInstance.guild_id == guild_id,
                ModuleInstance.module_key == "registration",
            )
        )
    ).scalar_one_or_none()
    if instance is None or instance.published_config_version_id is None:
        return None
    version = (
        await session.execute(
            select(ModuleConfigVersion).where(
                ModuleConfigVersion.id == instance.published_config_version_id,
                ModuleConfigVersion.module_instance_id == instance.id,
                ModuleConfigVersion.guild_id == guild_id,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        return None
    config = RegistrationConfig.model_validate(version.data or {})
    base_nickname = render_nickname(
        config.nickname_template,
        name=member.name,
        player_id=member.player_id_original,
    )
    fingerprint_data = {
        "identity_id": member.id,
        "status": member.status.value,
        "updated_at": member.updated_at.isoformat() if member.updated_at else "",
        "config_version": version.version,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return BaseMemberIdentity(
        identity_id=member.id,
        guild_id=guild_id,
        discord_user_id=discord_user_id,
        status=member.status,
        base_nickname=base_nickname,
        config_version=version.version,
        fingerprint=fingerprint,
    )
