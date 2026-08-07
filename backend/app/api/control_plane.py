from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.control_plane import get_or_create_state, publish, save_draft
from app.core.security import require_bot_token
from app.db import get_session
from app.models import ModuleConfigState
from app.schemas import (
    ModuleConfigDraftIn,
    ModuleConfigPublishIn,
    ModuleConfigStateOut,
    RevisionConflictOut,
)
from app.services import active_license_for_guild


router = APIRouter(
    prefix="/internal/control-plane",
    tags=["control-plane"],
    dependencies=[Depends(require_bot_token)],
)


def state_out(state: ModuleConfigState) -> ModuleConfigStateOut:
    return ModuleConfigStateOut(
        guild_id=state.guild_id,
        module_key=state.module_key,
        schema_version=state.schema_version,
        draft_data=state.draft_data or {},
        published_data=state.published_data or {},
        draft_revision=state.draft_revision,
        published_revision=state.published_revision,
        draft_updated_by=state.draft_updated_by,
        draft_updated_at=state.draft_updated_at,
        published_by=state.published_by,
        published_at=state.published_at,
    )


async def require_active_license(session: AsyncSession, guild_id: str) -> None:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")


@router.get(
    "/guilds/{guild_id}/modules/{module_key}",
    response_model=ModuleConfigStateOut,
)
async def read_state(
    guild_id: str,
    module_key: str,
    x_yuno_actor_id: Annotated[str, Header(min_length=1, max_length=32, pattern=r"^\d+$")],
    session: AsyncSession = Depends(get_session),
) -> ModuleConfigStateOut:
    del x_yuno_actor_id  # Identidade obrigatoria; leitura nao gera auditoria.
    await require_active_license(session, guild_id)
    state = await get_or_create_state(session, guild_id=guild_id, module_key=module_key)
    await session.commit()
    return state_out(state)


@router.put(
    "/guilds/{guild_id}/modules/{module_key}/draft",
    response_model=ModuleConfigStateOut,
    responses={409: {"model": RevisionConflictOut}},
)
async def write_draft(
    guild_id: str,
    module_key: str,
    data: ModuleConfigDraftIn,
    x_yuno_actor_id: Annotated[str, Header(min_length=1, max_length=32, pattern=r"^\d+$")],
    session: AsyncSession = Depends(get_session),
) -> ModuleConfigStateOut:
    await require_active_license(session, guild_id)
    state = await save_draft(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        data=data,
    )
    return state_out(state)


@router.post(
    "/guilds/{guild_id}/modules/{module_key}/publish",
    response_model=ModuleConfigStateOut,
    responses={409: {"model": RevisionConflictOut}},
)
async def publish_state(
    guild_id: str,
    module_key: str,
    data: ModuleConfigPublishIn,
    x_yuno_actor_id: Annotated[str, Header(min_length=1, max_length=32, pattern=r"^\d+$")],
    session: AsyncSession = Depends(get_session),
) -> ModuleConfigStateOut:
    await require_active_license(session, guild_id)
    state = await publish(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        data=data,
    )
    return state_out(state)
