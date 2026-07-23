from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import LicenseActivateIn, LicenseOut
from app.services import activate_license

router = APIRouter(prefix="/licenses", tags=["licenses"])


@router.post("/activate", response_model=LicenseOut)
async def activate(data: LicenseActivateIn, session: AsyncSession = Depends(get_session)) -> LicenseOut:
    try:
        license_record = await activate_license(
            session,
            license_key=data.license_key,
            guild_id=data.guild_id,
            guild_name=data.guild_name,
            owner_discord_id=data.owner_discord_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return LicenseOut(
        key=license_record.key,
        status=license_record.status,
        guild_id=license_record.guild_id,
        guild_name=license_record.guild_name,
        activated_at=license_record.activated_at,
    )
