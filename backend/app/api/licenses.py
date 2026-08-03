from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_token
from app.db import get_session
from app.models import License
from app.schemas import LicenseActivateIn, LicenseAdminOut, LicenseIssueIn, LicenseOut
from app.services import activate_license, issue_manual_license

router = APIRouter(prefix="/licenses", tags=["licenses"])


def admin_out(license_record: License) -> LicenseAdminOut:
    return LicenseAdminOut(
        key=license_record.key,
        status=license_record.status,
        guild_id=license_record.guild_id,
        guild_name=license_record.guild_name,
        activated_at=license_record.activated_at,
        owner_discord_id=license_record.owner_discord_id,
        payment_provider=license_record.payment_provider,
        payment_reference=license_record.payment_reference,
        created_at=license_record.created_at,
    )


@router.get("", response_model=list[LicenseAdminOut], dependencies=[Depends(require_admin_token)])
async def list_licenses(session: AsyncSession = Depends(get_session)) -> list[LicenseAdminOut]:
    result = await session.execute(select(License).order_by(License.created_at.desc()).limit(200))
    return [admin_out(item) for item in result.scalars().all()]


@router.post("/issue", response_model=LicenseAdminOut, dependencies=[Depends(require_admin_token)])
async def issue(data: LicenseIssueIn, session: AsyncSession = Depends(get_session)) -> LicenseAdminOut:
    try:
        license_record = await issue_manual_license(
            session,
            reference=data.reference,
            customer_name=data.customer_name,
            customer_email=data.customer_email,
            customer_discord_user_id=data.customer_discord_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return admin_out(license_record)


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
