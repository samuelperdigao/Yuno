from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.domain_modules.parceria.domain import ParceriaStatus, normalize_family
from app.domain_modules.parceria.models import Parceria, ParceriaFamily, ParceriaImage, ParceriaProduct
from app.models import GuildConfig, Parceria as LegacyParceria, ParceriaConfig as LegacyConfig


class ParceriaMigration:
    key = "parceria_domain_v1"

    async def inventory(self, session: Any, guild_id: str) -> dict[str, Any]:
        config = (await session.execute(select(LegacyConfig).where(LegacyConfig.guild_id == guild_id))).scalar_one_or_none()
        rows = list((await session.execute(select(LegacyParceria).where(LegacyParceria.guild_id == guild_id))).scalars())
        normalized: dict[str, int] = {}
        for row in rows:
            key = normalize_family(row.nome_familia)
            normalized[key] = normalized.get(key, 0) + 1
        return {
            "guild_id": guild_id,
            "legacy_config": config is not None,
            "legacy_partnerships": len(rows),
            "duplicate_normalized_families": sorted(key for key, count in normalized.items() if count > 1),
            "missing_images": [str(row.id) for row in rows if not row.nome_arquivo_imagem],
            "invalid_messages": [str(row.id) for row in rows if not row.mensagem_lista_id],
        }

    async def validate(self, session: Any, guild_id: str) -> list[str]:
        report = await self.inventory(session, guild_id)
        errors: list[str] = []
        if report["duplicate_normalized_families"]:
            errors.append("Existem duplicidades após normalização de família.")
        if report["missing_images"]:
            errors.append("Existem parcerias sem imagem legada.")
        if report["invalid_messages"]:
            errors.append("Existem parcerias sem referência válida de mensagem.")
        config = (await session.execute(select(LegacyConfig).where(LegacyConfig.guild_id == guild_id))).scalar_one_or_none()
        settings = None
        if config:
            guild_config = (await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))).scalar_one_or_none()
            settings = (guild_config.settings or {}).get("parceria") if guild_config else None
        if not (settings or {}).get("manager_role_ids"):
            errors.append("Guild sem cargos gerentes definidos para Parcerias.")
        return errors


async def backfill_legacy(session: Any, *, guild_id: str, correlation_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Backfill repetível: só cria dados novos e nunca apaga os legados."""

    legacy_rows = list((await session.execute(select(LegacyParceria).where(LegacyParceria.guild_id == guild_id).order_by(LegacyParceria.id))).scalars())
    created = 0
    skipped = 0
    conflicts: list[str] = []
    for row in legacy_rows:
        existing = (await session.execute(select(Parceria).where(Parceria.guild_id == guild_id, Parceria.legacy_id == row.id))).scalar_one_or_none()
        if existing:
            skipped += 1
            continue
        normalized = normalize_family(row.nome_familia)
        family = (await session.execute(select(ParceriaFamily).where(ParceriaFamily.guild_id == guild_id, ParceriaFamily.name_normalized == normalized))).scalar_one_or_none()
        if family is not None:
            conflicts.append(str(row.id))
            continue
        if dry_run:
            created += 1
            continue
        family = ParceriaFamily(guild_id=guild_id, name=row.nome_familia, name_normalized=normalized, active=bool(row.ativo), legacy_id=row.id)
        image = ParceriaImage(guild_id=guild_id, storage_key=f"legacy:{guild_id}:{row.id}:{row.nome_arquivo_imagem or 'missing'}", storage_url=None, content_type="application/octet-stream", size_bytes=0, original_filename=row.nome_arquivo_imagem, uploaded_by=row.registrado_por)
        session.add_all([family, image])
        await session.flush()
        item = Parceria(guild_id=guild_id, family_id=family.id, status=ParceriaStatus.active if row.ativo else ParceriaStatus.inactive, registered_by=row.registrado_por, image_asset_id=image.id, public_message_id=row.mensagem_lista_id, legacy_id=row.id)
        session.add(item)
        await session.flush()
        session.add(ParceriaProduct(guild_id=guild_id, parceria_id=item.id, name=row.produto))
        created += 1
    return {"guild_id": guild_id, "created": created, "skipped": skipped, "conflicts": conflicts, "dry_run": dry_run}
