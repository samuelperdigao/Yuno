from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_or_bot_token, require_admin_token, require_bot_token
from app.db import get_session
from app.models import SystemRecord
from app.schemas import MODULES, SystemRecordIn, SystemRecordOut, SystemRecordPatch
from app.services import active_license_for_guild, audit

router = APIRouter(prefix="/systems", tags=["systems"])


def assert_module(module: str) -> None:
    if module not in MODULES:
        raise HTTPException(status_code=404, detail="Modulo nao existe.")


def record_out(record: SystemRecord) -> SystemRecordOut:
    return SystemRecordOut(
        id=record.id,
        guild_id=record.guild_id,
        module=record.module,
        status=record.status,
        title=record.title,
        requester_id=record.requester_id,
        reviewer_id=record.reviewer_id,
        channel_id=record.channel_id,
        payload=record.payload or {},
        created_at=record.created_at,
        reviewed_at=record.reviewed_at,
    )


@router.post("/{module}/records", response_model=SystemRecordOut, dependencies=[Depends(require_bot_token)])
async def create_record(module: str, data: SystemRecordIn, session: AsyncSession = Depends(get_session)) -> SystemRecordOut:
    assert_module(module)
    if not await active_license_for_guild(session, data.guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")
    record = SystemRecord(
        guild_id=data.guild_id,
        module=module,
        title=data.title,
        requester_id=data.requester_id,
        channel_id=data.channel_id,
        payload=data.payload,
    )
    session.add(record)
    await session.flush()
    await audit(
        session,
        action=f"{module}.record.created",
        entity_type="system_record",
        entity_id=str(record.id),
        guild_id=data.guild_id,
        actor_id=data.requester_id,
        payload=data.payload,
    )
    await session.commit()
    return record_out(record)


@router.get("/{module}/records", response_model=list[SystemRecordOut], dependencies=[Depends(require_admin_token)])
async def list_records(module: str, guild_id: str, session: AsyncSession = Depends(get_session)) -> list[SystemRecordOut]:
    assert_module(module)
    result = await session.execute(
        select(SystemRecord).where(SystemRecord.guild_id == guild_id, SystemRecord.module == module).order_by(SystemRecord.created_at.desc())
    )
    return [record_out(record) for record in result.scalars()]


@router.get("/{module}/records/{record_id}", response_model=SystemRecordOut, dependencies=[Depends(require_admin_or_bot_token)])
async def get_record(module: str, record_id: int, session: AsyncSession = Depends(get_session)) -> SystemRecordOut:
    assert_module(module)
    record = await session.get(SystemRecord, record_id)
    if not record or record.module != module:
        raise HTTPException(status_code=404, detail="Registro nao encontrado.")
    return record_out(record)


@router.patch("/{module}/records/{record_id}", response_model=SystemRecordOut, dependencies=[Depends(require_admin_or_bot_token)])
async def patch_record(module: str, record_id: int, data: SystemRecordPatch, session: AsyncSession = Depends(get_session)) -> SystemRecordOut:
    assert_module(module)
    record = await session.get(SystemRecord, record_id)
    if not record or record.module != module:
        raise HTTPException(status_code=404, detail="Registro nao encontrado.")
    record.status = data.status
    record.reviewer_id = data.reviewer_id
    record.reviewed_at = datetime.now(timezone.utc)
    if data.payload is not None:
        record.payload = {**(record.payload or {}), **data.payload}
    await audit(
        session,
        action=f"{module}.record.{data.status}",
        entity_type="system_record",
        entity_id=str(record.id),
        guild_id=record.guild_id,
        actor_id=data.reviewer_id,
        payload=record.payload,
    )
    await session.commit()
    return record_out(record)
