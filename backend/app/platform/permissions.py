from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.lifecycle import ensure_module_instance
from app.platform.models import GuildAdminRole, ModulePermissionGrant
from app.platform.registry import module_registry
from app.platform.schemas import ActorContextIn, AuthorizationOut


def _scope_matches(grant: ModulePermissionGrant, actor: ActorContextIn, resource_id: str) -> bool:
    if grant.scope_type == "guild":
        return True
    if grant.scope_type == "resource":
        return bool(resource_id) and grant.scope_id == resource_id
    if grant.scope_type == "channel":
        return bool(actor.channel_id) and grant.scope_id == actor.channel_id
    if grant.scope_type == "category":
        return bool(actor.category_id) and grant.scope_id == actor.category_id
    return False


def _subject_matches(grant: ModulePermissionGrant, actor: ActorContextIn) -> bool:
    if grant.subject_type == "everyone":
        return actor.actor_type == "user"
    if grant.subject_type == "system":
        return actor.actor_type == "system"
    if grant.subject_type == "user":
        return bool(actor.user_id) and grant.subject_id == actor.user_id
    if grant.subject_type == "role":
        return grant.subject_id in actor.role_ids
    return False


async def authorize(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    capability_key: str,
    actor: ActorContextIn,
    resource_id: str = "",
) -> AuthorizationOut:
    definition = module_registry.get(module_key)
    capability = definition.capability(capability_key) if definition else None
    if capability is None:
        return AuthorizationOut(allowed=False, reason="Capability desconhecida.")
    if actor.guild_id != guild_id:
        return AuthorizationOut(allowed=False, reason="ActorContext pertence a outra guild.")

    if actor.is_guild_owner or "administrator" in actor.discord_permissions:
        return AuthorizationOut(allowed=True, reason="Superadministrador da guild.")
    if actor.actor_type == "system":
        return AuthorizationOut(
            allowed=capability.allow_automation,
            reason="Automacao autorizada." if capability.allow_automation else capability.denial_reason,
        )
    if capability.allow_resource_owner and actor.user_id == actor.resource_owner_id:
        return AuthorizationOut(allowed=True, reason="Dono do recurso.")

    admin_role_ids = set(
        (
            await session.execute(
                select(GuildAdminRole.role_id).where(GuildAdminRole.guild_id == guild_id)
            )
        ).scalars()
    )
    central_admin = "manage_guild" in actor.discord_permissions or bool(
        admin_role_ids.intersection(actor.role_ids)
    )
    if central_admin and (capability.administrative or capability.admin_bypass):
        return AuthorizationOut(allowed=True, reason="Administrador autorizado para esta capability.")

    instance = await ensure_module_instance(session, guild_id=guild_id, module_key=module_key)
    if instance.published_config_version_id is None:
        return AuthorizationOut(allowed=False, reason="Modulo sem permissoes publicadas.")
    grants = (
        await session.execute(
            select(ModulePermissionGrant).where(
                ModulePermissionGrant.guild_id == guild_id,
                ModulePermissionGrant.module_instance_id == instance.id,
                ModulePermissionGrant.config_version_id == instance.published_config_version_id,
                ModulePermissionGrant.capability == capability_key,
            )
        )
    ).scalars().all()
    allowed = any(
        _subject_matches(grant, actor) and _scope_matches(grant, actor, resource_id)
        for grant in grants
    )
    return AuthorizationOut(
        allowed=allowed,
        reason="Grant publicado encontrado." if allowed else capability.denial_reason,
    )
