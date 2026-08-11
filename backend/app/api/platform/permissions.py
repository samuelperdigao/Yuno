from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.permissions import authorize
from app.platform.schemas import AuthorizationIn, AuthorizationOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


@router.post("/guilds/{guild_id}/modules/{module_key}/authorize", response_model=AuthorizationOut)
async def authorize_action(
    guild_id: str,
    module_key: str,
    data: AuthorizationIn,
    session: AsyncSession = Depends(get_session),
) -> AuthorizationOut:
    await require_active_license(session, guild_id)
    return await authorize(
        session,
        guild_id=guild_id,
        module_key=module_key,
        capability_key=data.capability,
        actor=data.actor,
        resource_id=data.resource_id,
    )
