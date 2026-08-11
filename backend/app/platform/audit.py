from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.models import AuditEntry


SENSITIVE_PARTS = ("token", "secret", "password", "authorization", "webhook")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(part in key.lower() for part in SENSITIVE_PARTS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


async def write_audit(
    session: AsyncSession,
    *,
    guild_id: str,
    action: str,
    resource_type: str,
    correlation_id: str | None = None,
    actor_type: str = "user",
    actor_id: str | None = None,
    module_key: str | None = None,
    resource_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    config_version: int | None = None,
    result: str = "success",
    metadata: dict | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        guild_id=guild_id,
        actor_type=actor_type,
        actor_id=actor_id,
        module_key=module_key,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=redact(before or {}),
        after=redact(after or {}),
        config_version=config_version,
        result=result,
        correlation_id=correlation_id or str(uuid4()),
        metadata_json=redact(metadata or {}),
    )
    session.add(entry)
    await session.flush()
    return entry
