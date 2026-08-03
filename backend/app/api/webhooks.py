from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_session
from app.schemas import MercadoPagoWebhookOut
from app.services import create_pending_license_from_payment

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/mercadopago", response_model=MercadoPagoWebhookOut)
async def mercado_pago_webhook(
    request: Request,
    x_yuno_webhook_secret: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> MercadoPagoWebhookOut:
    settings = get_settings()
    if not settings.mercado_pago_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook Mercado Pago nao configurado.")
    if not x_yuno_webhook_secret or not compare_digest(x_yuno_webhook_secret, settings.mercado_pago_webhook_secret):
        raise HTTPException(status_code=401, detail="Webhook nao autorizado.")

    payload = await request.json()
    status = payload.get("status") or payload.get("data", {}).get("status")
    reference = str(payload.get("external_reference") or payload.get("id") or payload.get("data", {}).get("id") or "")
    if status not in {"approved", "paid"}:
        return MercadoPagoWebhookOut(accepted=False)
    if not reference:
        raise HTTPException(status_code=400, detail="Webhook sem referencia de pagamento.")

    license_record, duplicate = await create_pending_license_from_payment(session, reference=reference, payload=payload)
    await session.commit()
    return MercadoPagoWebhookOut(accepted=True, license_key=license_record.key, duplicate=duplicate)
