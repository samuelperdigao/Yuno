from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.interactions import begin_interaction, finish_interaction
from app.platform.schemas import InteractionBeginIn, InteractionCompleteIn, InteractionReceiptOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


@router.post("/guilds/{guild_id}/interactions/begin", response_model=InteractionReceiptOut)
async def begin(
    guild_id: str,
    data: InteractionBeginIn,
    session: AsyncSession = Depends(get_session),
) -> InteractionReceiptOut:
    await require_active_license(session, guild_id)
    receipt, duplicate = await begin_interaction(session, guild_id=guild_id, **data.model_dump())
    return InteractionReceiptOut(
        receipt_id=receipt.id,
        duplicate=duplicate,
        state=receipt.state,
        result=receipt.result or {},
    )


@router.post("/guilds/{guild_id}/interactions/{receipt_id}/finish", response_model=InteractionReceiptOut)
async def finish(
    guild_id: str,
    receipt_id: str,
    data: InteractionCompleteIn,
    session: AsyncSession = Depends(get_session),
) -> InteractionReceiptOut:
    await require_active_license(session, guild_id)
    receipt = await finish_interaction(
        session, guild_id=guild_id, receipt_id=receipt_id, **data.model_dump()
    )
    if receipt is None:
        raise HTTPException(status_code=404, detail="Interacao nao encontrada nesta guild.")
    return InteractionReceiptOut(
        receipt_id=receipt.id,
        duplicate=False,
        state=receipt.state,
        result=receipt.result or {},
    )
