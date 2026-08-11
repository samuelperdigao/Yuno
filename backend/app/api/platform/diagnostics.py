from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.diagnostics import module_health, platform_health
from app.platform.schemas import HealthCheckOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


@router.get("/diagnostics", response_model=list[HealthCheckOut])
async def platform_diagnostics(session: AsyncSession = Depends(get_session)) -> list[HealthCheckOut]:
    return await platform_health(session)


@router.get("/guilds/{guild_id}/modules/{module_key}/diagnostics", response_model=list[HealthCheckOut])
async def module_diagnostics(
    guild_id: str,
    module_key: str,
    session: AsyncSession = Depends(get_session),
) -> list[HealthCheckOut]:
    await require_active_license(session, guild_id)
    checks = await module_health(session, guild_id=guild_id, module_key=module_key)
    await session.commit()
    return checks
