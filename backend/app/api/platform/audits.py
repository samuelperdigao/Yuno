from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.models import AuditEntry
from app.platform.schemas import AuditEntryOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


@router.get("/guilds/{guild_id}/audit", response_model=list[AuditEntryOut])
async def list_audit(
    guild_id: str,
    module_key: str | None = None,
    correlation_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[AuditEntryOut]:
    await require_active_license(session, guild_id)
    query = select(AuditEntry).where(AuditEntry.guild_id == guild_id)
    if module_key:
        query = query.where(AuditEntry.module_key == module_key)
    if correlation_id:
        query = query.where(AuditEntry.correlation_id == correlation_id)
    entries = list(
        (await session.execute(query.order_by(AuditEntry.created_at.desc()).limit(limit))).scalars()
    )
    return [
        AuditEntryOut(
            id=item.id,
            guild_id=item.guild_id,
            actor_type=item.actor_type,
            actor_id=item.actor_id,
            module_key=item.module_key,
            action=item.action,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            before=item.before or {},
            after=item.after or {},
            config_version=item.config_version,
            result=item.result,
            correlation_id=item.correlation_id,
            metadata=item.metadata_json or {},
            created_at=item.created_at,
        )
        for item in entries
    ]
