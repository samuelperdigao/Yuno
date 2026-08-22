from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.farm_tickets import services
from app.domain_modules.farm_tickets.domain import (
    ProofNoLongerEligible,
    ProofStorageState,
)
from app.domain_modules.farm_tickets.models import (
    FarmTicket,
    FarmTicketEntry,
    FarmTicketPendingOperation,
    FarmTicketProof,
)
from app.object_storage import ObjectStorage

MAX_PROOF_SIZE = 20 * 1024 * 1024
MAX_PROOF_PROCESSING_ATTEMPTS = 10
ALLOWED_IMAGE_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class InvalidProofImage(ValueError):
    pass


async def _download_to_temp(url: str, *, expected_max: int = MAX_PROOF_SIZE) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix="yuno-proof-", suffix=".upload")
    os.close(descriptor)
    path = Path(raw_path)
    size = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with path.open("wb") as output:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        size += len(chunk)
                        if size > expected_max:
                            raise InvalidProofImage("A imagem excede 20 MiB.")
                        output.write(chunk)
        if size == 0:
            raise InvalidProofImage("O arquivo de comprovante esta vazio.")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _inspect_image(path: Path) -> tuple[str, int, str]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - protegido pelo requirements
        raise RuntimeError("Dependencia Pillow nao instalada.") from exc
    try:
        with Image.open(path) as image:
            image.verify()
            image_format = str(image.format or "").upper()
        content_type = ALLOWED_IMAGE_FORMATS.get(image_format)
        if content_type is None:
            raise InvalidProofImage("Formato de imagem nao aceito.")
        with Image.open(path) as image:
            width, height = image.size
            if width < 1 or height < 1:
                raise InvalidProofImage("Imagem sem dimensoes validas.")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidProofImage("O arquivo nao e uma imagem valida.") from exc
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            size += len(chunk)
            checksum.update(chunk)
    return content_type, size, checksum.hexdigest()


async def process_claimed_proof(
    session: AsyncSession,
    *,
    storage: ObjectStorage,
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    claim_token: str,
) -> dict[str, Any]:
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation).where(
                FarmTicketPendingOperation.guild_id == guild_id,
                FarmTicketPendingOperation.ticket_id == ticket_id,
                FarmTicketPendingOperation.id == operation_id,
                FarmTicketPendingOperation.claim_token == claim_token,
            )
        )
    ).scalar_one_or_none()
    if operation is None or not operation.attachment_url:
        raise services.FarmTicketConflict("Claim de comprovante nao encontrado.")
    await services.mark_proof_processing(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        operation_id=operation_id,
        claim_token=claim_token,
    )
    path: Path | None = None
    try:
        path = await _download_to_temp(operation.attachment_url)
        content_type, size, checksum = _inspect_image(path)
        ticket = await session.get(FarmTicket, ticket_id)
        entry = await session.get(FarmTicketEntry, operation.pending_entry_id)
        if ticket is None or entry is None:
            raise services.FarmTicketConflict(
                "Ticket ou lancamento pendente nao encontrado."
            )
        key = (
            f"{guild_id}/{ticket.meta_cycle_id}/{ticket.id}/{entry.id}/proof/"
            f"{operation.proof_message_id}-{operation.proof_attachment_id}"
        )
        await storage.put_file(
            key=key,
            path=path,
            content_type=content_type,
            metadata={
                "sha256": checksum,
                "ticket-id": ticket.id,
                "operation-id": operation.id,
            },
        )
        try:
            return await services.confirm_proof(
                session,
                guild_id=guild_id,
                ticket_id=ticket_id,
                operation_id=operation_id,
                claim_token=claim_token,
                object_key=key,
                checksum_sha256=checksum,
                size_bytes=size,
                content_type=content_type,
            )
        except ProofNoLongerEligible as exc:
            # O upload pode ter terminado enquanto o evento de ciclo/participacao
            # fechava a janela. Removemos o objeto antes de resolver o claim.
            await storage.delete(key=key)
            return await services.reject_invalid_proof(
                session,
                guild_id=guild_id,
                ticket_id=ticket_id,
                operation_id=operation_id,
                claim_token=claim_token,
                reason=str(exc),
                now=operation.proof_deadline + timedelta(microseconds=1),
            )
    except InvalidProofImage as exc:
        return await services.reject_invalid_proof(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            operation_id=operation_id,
            claim_token=claim_token,
            reason=str(exc),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if operation.attempts >= MAX_PROOF_PROCESSING_ATTEMPTS:
            await services.fail_operation_definitively(
                session,
                guild_id=guild_id,
                operation_id=operation_id,
                error=error,
            )
        else:
            await services.retry_proof(
                session,
                guild_id=guild_id,
                ticket_id=ticket_id,
                operation_id=operation_id,
                claim_token=claim_token,
                error=error,
            )
        raise
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def mark_thread_delivery(
    session: AsyncSession, *, guild_id: str, proof_id: str
) -> None:
    proof = (
        await session.execute(
            select(FarmTicketProof).where(
                FarmTicketProof.guild_id == guild_id,
                FarmTicketProof.id == proof_id,
            )
        )
    ).scalar_one_or_none()
    if proof is None:
        raise services.FarmTicketNotFound("Comprovante nao encontrado.")
    proof.thread_delivery_confirmed_at = services.utc_now()
    await session.commit()


async def cleanup_released_ticket_proofs(
    session: AsyncSession,
    *,
    storage: ObjectStorage,
    guild_id: str,
    ticket_id: str,
) -> dict[str, int]:
    ticket = await session.get(FarmTicket, ticket_id)
    if ticket is None or ticket.guild_id != guild_id:
        raise services.FarmTicketNotFound("Ticket nao encontrado.")
    if ticket.binding_released_at is None:
        raise services.FarmTicketConflict(
            "Ticket ainda operacional; cleanup bloqueado."
        )
    proofs = list(
        (
            await session.execute(
                select(FarmTicketProof).where(
                    FarmTicketProof.guild_id == guild_id,
                    FarmTicketProof.ticket_id == ticket_id,
                    FarmTicketProof.storage_state.in_(
                        [
                            ProofStorageState.STORED,
                            ProofStorageState.DELETE_PENDING,
                            ProofStorageState.RETAINED,
                        ]
                    ),
                )
            )
        ).scalars()
    )
    deleted = 0
    retained = 0
    for proof in proofs:
        if proof.thread_delivery_confirmed_at is None:
            proof.storage_state = ProofStorageState.RETAINED
            proof.cleanup_error = "Copia na thread ainda nao confirmada."
            retained += 1
            continue
        proof.storage_state = ProofStorageState.DELETE_PENDING
        await session.commit()
        try:
            await storage.delete(key=proof.object_key)
        except Exception as exc:
            proof.cleanup_error = f"{type(exc).__name__}: {exc}"[:2000]
            await session.commit()
            continue
        proof.storage_state = ProofStorageState.DELETED
        proof.cleanup_error = None
        deleted += 1
        await session.commit()
    return {"deleted": deleted, "retained": retained}
