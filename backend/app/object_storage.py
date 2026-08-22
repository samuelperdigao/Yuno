from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings, get_settings


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorage(Protocol):
    async def put_file(
        self,
        *,
        key: str,
        path: Path,
        content_type: str,
        metadata: dict[str, str],
    ) -> None: ...

    async def delete(self, *, key: str) -> None: ...

    async def presign_get(
        self, *, key: str, expires_seconds: int | None = None
    ) -> str: ...

    async def head(self, *, key: str) -> dict: ...


@dataclass(frozen=True)
class S3StorageConfig:
    endpoint: str
    region: str
    bucket: str
    access_key: str
    secret_key: str
    path_style: bool = True
    sse: str = ""
    presign_seconds: int = 300

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3StorageConfig":
        required = {
            "OBJECT_STORAGE_ENDPOINT": settings.object_storage_endpoint,
            "OBJECT_STORAGE_BUCKET": settings.object_storage_bucket,
            "OBJECT_STORAGE_ACCESS_KEY": settings.object_storage_access_key,
            "OBJECT_STORAGE_SECRET_KEY": settings.object_storage_secret_key,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ObjectStorageError(
                "Object Storage nao configurado: " + ", ".join(sorted(missing))
            )
        return cls(
            endpoint=settings.object_storage_endpoint,
            region=settings.object_storage_region,
            bucket=settings.object_storage_bucket,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
            path_style=settings.object_storage_path_style,
            sse=settings.object_storage_sse,
            presign_seconds=settings.object_storage_presign_seconds,
        )


class S3ObjectStorage:
    """Adapter S3 privado; boto3 roda fora do event loop e recebe arquivos por path."""

    def __init__(self, config: S3StorageConfig):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - protegido pelo requirements
            raise ObjectStorageError("Dependencia boto3 nao instalada.") from exc
        self.config = config
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            region_name=config.region,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            config=Config(
                s3={"addressing_style": "path" if config.path_style else "virtual"}
            ),
        )

    async def put_file(
        self,
        *,
        key: str,
        path: Path,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        extra: dict = {"ContentType": content_type, "Metadata": metadata}
        if self.config.sse:
            extra["ServerSideEncryption"] = self.config.sse
        await asyncio.to_thread(
            self._client.upload_file,
            str(path),
            self.config.bucket,
            key,
            ExtraArgs=extra,
        )

    async def delete(self, *, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self.config.bucket, Key=key
        )

    async def presign_get(self, *, key: str, expires_seconds: int | None = None) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.config.bucket, "Key": key},
            ExpiresIn=expires_seconds or self.config.presign_seconds,
        )

    async def head(self, *, key: str) -> dict:
        return await asyncio.to_thread(
            self._client.head_object, Bucket=self.config.bucket, Key=key
        )


def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage(S3StorageConfig.from_settings(get_settings()))
