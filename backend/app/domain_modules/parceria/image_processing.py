from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.domain_modules.parceria.domain import MAX_IMAGE_BYTES
from app.object_storage import ObjectStorage


DISCORD_ATTACHMENT_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}


class InvalidPartnershipImage(ValueError):
    """A imagem recebida nao e um anexo Discord valido para Parcerias."""


@dataclass(frozen=True)
class StoredPartnershipImage:
    storage_key: str
    content_type: str
    size_bytes: int
    checksum: str
    original_filename: str | None


def _allowed_discord_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    return parsed.scheme == "https" and (
        hostname in DISCORD_ATTACHMENT_HOSTS
        or hostname.endswith(".discordapp.com")
        or hostname.endswith(".discordapp.net")
    )


def _inspect_image(path: Path) -> tuple[str, int, str]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - dependÃªncia da imagem
        raise RuntimeError("Dependencia Pillow nao instalada.") from exc

    try:
        with Image.open(path) as image:
            image.verify()
            image_format = str(image.format or "").upper()
        content_type = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
        }.get(image_format)
        if content_type is None:
            raise InvalidPartnershipImage("Formato de imagem nao aceito.")
        with Image.open(path) as image:
            width, height = image.size
            if width < 1 or height < 1:
                raise InvalidPartnershipImage("Imagem sem dimensoes validas.")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidPartnershipImage("O arquivo nao e uma imagem valida.") from exc

    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            size += len(chunk)
            checksum.update(chunk)
    if size <= 0:
        raise InvalidPartnershipImage("A imagem esta vazia.")
    if size > MAX_IMAGE_BYTES:
        raise InvalidPartnershipImage("A imagem excede o limite de 8 MiB.")
    return content_type, size, checksum.hexdigest()


async def ingest_discord_attachment(
    storage: ObjectStorage,
    *,
    source_url: str,
    storage_key: str,
    original_filename: str | None,
) -> StoredPartnershipImage:
    if not _allowed_discord_url(source_url):
        raise InvalidPartnershipImage("A origem da imagem precisa ser um anexo HTTPS do Discord.")

    descriptor, raw_path = tempfile.mkstemp(prefix="yuno-parceria-", suffix=".upload")
    os.close(descriptor)
    path = Path(raw_path)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            async with client.stream("GET", source_url) as response:
                response.raise_for_status()
                if not _allowed_discord_url(str(response.url)):
                    raise InvalidPartnershipImage("O anexo redirecionou para uma origem nao permitida.")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        announced_size = int(content_length)
                    except ValueError as exc:
                        raise InvalidPartnershipImage("O anexo informou um tamanho invalido.") from exc
                    if announced_size > MAX_IMAGE_BYTES:
                        raise InvalidPartnershipImage("A imagem excede o limite de 8 MiB.")
                size = 0
                with path.open("wb") as output:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise InvalidPartnershipImage("A imagem excede o limite de 8 MiB.")
                        output.write(chunk)

        content_type, size, checksum = _inspect_image(path)
        await storage.put_file(
            key=storage_key,
            path=path,
            content_type=content_type,
            metadata={"sha256": checksum, "source": "discord-attachment"},
        )
        return StoredPartnershipImage(
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=size,
            checksum=checksum,
            original_filename=original_filename,
        )
    finally:
        path.unlink(missing_ok=True)
