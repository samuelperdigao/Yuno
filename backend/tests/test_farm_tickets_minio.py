"""Integracao real e opt-in com o bucket privado usado por Tickets V2."""

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.object_storage import S3ObjectStorage, S3StorageConfig  # noqa: E402

MINIO_ENDPOINT = os.getenv("YUNO_TEST_MINIO_ENDPOINT")
MINIO_BUCKET = os.getenv("YUNO_TEST_MINIO_BUCKET")
MINIO_ACCESS_KEY = os.getenv("YUNO_TEST_MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("YUNO_TEST_MINIO_SECRET_KEY")


@pytest.mark.skipif(
    not all([MINIO_ENDPOINT, MINIO_BUCKET, MINIO_ACCESS_KEY, MINIO_SECRET_KEY]),
    reason=(
        "Defina YUNO_TEST_MINIO_ENDPOINT/BUCKET/ACCESS_KEY/SECRET_KEY para "
        "validar o Object Storage real."
    ),
)
def test_minio_private_stream_checksum_retry_restart_and_cleanup(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        assert MINIO_ENDPOINT
        assert MINIO_BUCKET
        assert MINIO_ACCESS_KEY
        assert MINIO_SECRET_KEY
        config = S3StorageConfig(
            endpoint=MINIO_ENDPOINT,
            region=os.getenv("YUNO_TEST_MINIO_REGION", "us-east-1"),
            bucket=MINIO_BUCKET,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            path_style=True,
            presign_seconds=60,
        )
        storage = S3ObjectStorage(config)
        source = tmp_path / "proof.png"
        # PNG 1x1 conhecido; pequeno o bastante para validar byte a byte.
        source.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                "0000000d49444154789c6360f8cfc00000040101005fe5c34b0000000049454e44"
                "ae426082"
            )
        )
        payload = source.read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        key = f"acceptance-guild/cycle/ticket/entry/proof/{uuid4().hex}.png"
        unsigned_url = f"{MINIO_ENDPOINT.rstrip('/')}/{MINIO_BUCKET}/{key}"
        try:
            await storage.put_file(
                key=key,
                path=source,
                content_type="image/png",
                metadata={"sha256": checksum, "ticket-id": "acceptance-ticket"},
            )
            # Repetir o mesmo upload simula retry idempotente antes do commit SQL.
            await storage.put_file(
                key=key,
                path=source,
                content_type="image/png",
                metadata={"sha256": checksum, "ticket-id": "acceptance-ticket"},
            )
            head = await storage.head(key=key)
            assert head["ContentLength"] == len(payload)
            assert head["ContentType"] == "image/png"
            assert head["Metadata"]["sha256"] == checksum

            # Uma nova instancia representa restart do processo/API.
            restarted = S3ObjectStorage(config)
            assert (await restarted.head(key=key))["Metadata"]["sha256"] == checksum
            signed_url = await restarted.presign_get(key=key, expires_seconds=60)
            async with httpx.AsyncClient(timeout=15.0) as client:
                signed = await client.get(signed_url)
                unsigned = await client.get(unsigned_url)
            assert signed.status_code == 200
            assert signed.content == payload
            assert unsigned.status_code in {401, 403}

            await restarted.delete(key=key)
            with pytest.raises(ClientError):
                await restarted.head(key=key)
        finally:
            # Cleanup idempotente caso uma assercao intermediaria falhe.
            await storage.delete(key=key)

    asyncio.run(scenario())
