from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.anuncio.domain import (
    AnuncioDomainError,
    normalize_content,
    normalize_title,
)
from app.domain_modules.anuncio.schemas import AnuncioConfig
from app.platform.audit import write_audit
from app.platform.models import ModuleConfigVersion, ModuleInstance, ModuleLifecycle

log = logging.getLogger("yuno.anuncio")


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _published_configuration(
    session: AsyncSession, guild_id: str, *, require_active: bool = True
) -> tuple[ModuleInstance, ModuleConfigVersion, AnuncioConfig]:
    query = (
        select(ModuleInstance, ModuleConfigVersion)
        .join(
            ModuleConfigVersion,
            ModuleConfigVersion.id == ModuleInstance.published_config_version_id,
        )
        .where(
            ModuleInstance.guild_id == guild_id,
            ModuleInstance.module_key == "anuncio",
            ModuleConfigVersion.guild_id == guild_id,
            ModuleConfigVersion.module_key == "anuncio",
        )
    )
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise _http(409, "anuncio.not_configured", "Anúncio ainda não foi publicado.")
    instance, version = row
    if require_active and instance.lifecycle != ModuleLifecycle.active:
        raise _http(409, "anuncio.not_active", "Anúncio não está ativo.")
    config = AnuncioConfig.model_validate(version.data or {})
    if require_active and not config.enabled:
        raise _http(409, "anuncio.disabled", "Anúncio está desabilitado.")
    return instance, version, config


async def effective_configuration(
    session: AsyncSession, *, guild_id: str, require_active: bool = True
) -> tuple[ModuleConfigVersion, AnuncioConfig]:
    _, version, config = await _published_configuration(
        session, guild_id, require_active=require_active
    )
    return version, config


async def publish_announcement(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    correlation_id: str,
    titulo: str,
    conteudo: str,
    mencionar_everyone: bool,
    anexou_arquivo: bool,
) -> tuple[AnuncioConfig, int]:
    _, version, config = await _published_configuration(session, guild_id)
    try:
        titulo_normalizado = normalize_title(titulo)
        conteudo_normalizado = normalize_content(conteudo)
    except AnuncioDomainError as exc:
        raise _http(422, "anuncio.invalid_input", str(exc)) from exc

    await write_audit(
        session,
        guild_id=guild_id,
        module_key="anuncio",
        actor_type="user",
        actor_id=actor_id,
        action="anuncio.published",
        resource_type="announcement",
        correlation_id=correlation_id,
        after={
            "titulo": titulo_normalizado,
            "conteudo_length": len(conteudo_normalizado),
            "canal_id": config.channel_id,
            "mencionou_everyone": mencionar_everyone,
            "anexou_arquivo": anexou_arquivo,
        },
        config_version=version.version,
    )
    await session.commit()
    return config, version.version
