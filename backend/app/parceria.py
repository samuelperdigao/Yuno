import unicodedata
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Parceria, ParceriaConfig
from app.schemas import ParceriaConfigIn, ParceriaCreateIn, ParceriaUpdateIn
from app.services import get_or_create_config


def normalize_nome_familia(nome_familia: str) -> str:
    normalized = unicodedata.normalize("NFKD", nome_familia.strip())
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


async def get_config(session: AsyncSession, guild_id: str) -> ParceriaConfig | None:
    result = await session.execute(select(ParceriaConfig).where(ParceriaConfig.guild_id == guild_id))
    return result.scalar_one_or_none()


async def upsert_config(session: AsyncSession, guild_id: str, data: ParceriaConfigIn) -> ParceriaConfig:
    config = await get_config(session, guild_id)
    if not config:
        config = ParceriaConfig(guild_id=guild_id)
        session.add(config)
    config.category_id = data.category_id
    config.registrar_channel_id = data.registrar_channel_id
    config.ativas_channel_id = data.ativas_channel_id
    config.panel_message_id = data.panel_message_id

    # Espelha em guild_config.settings, mesma convencao do farm_tickets: e o
    # que permite o dashboard (Fase 1) ler o estado de todo modulo por um so
    # lugar, sem precisar saber que parceria tem tabela propria.
    guild_config = await get_or_create_config(session, guild_id)
    settings = dict(guild_config.settings or {})
    settings["parceria"] = {
        "category_id": data.category_id,
        "registrar_channel_id": data.registrar_channel_id,
        "ativas_channel_id": data.ativas_channel_id,
        "panel_message_id": data.panel_message_id,
    }
    guild_config.settings = settings
    return config


async def find_by_name(session: AsyncSession, guild_id: str, nome_familia: str) -> Parceria | None:
    result = await session.execute(
        select(Parceria).where(
            Parceria.guild_id == guild_id,
            Parceria.nome_familia_normalizado == normalize_nome_familia(nome_familia),
        )
    )
    return result.scalar_one_or_none()


async def name_exists_for_other(session: AsyncSession, guild_id: str, nome_familia: str, parceria_id: int) -> bool:
    result = await session.execute(
        select(Parceria.id).where(
            Parceria.guild_id == guild_id,
            Parceria.nome_familia_normalizado == normalize_nome_familia(nome_familia),
            Parceria.id != parceria_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def list_active(session: AsyncSession, guild_id: str) -> list[Parceria]:
    result = await session.execute(
        select(Parceria)
        .where(Parceria.guild_id == guild_id, Parceria.ativo.is_(True))
        .order_by(func.lower(Parceria.nome_familia_normalizado))
    )
    return list(result.scalars())


async def get_parceria(session: AsyncSession, parceria_id: int) -> Parceria:
    parceria = await session.get(Parceria, parceria_id)
    if not parceria:
        raise HTTPException(status_code=404, detail="Parceria nao encontrada.")
    return parceria


async def create_parceria(session: AsyncSession, guild_id: str, data: ParceriaCreateIn) -> Parceria:
    if await find_by_name(session, guild_id, data.nome_familia):
        raise HTTPException(status_code=409, detail="Ja existe parceria registrada com esse nome de familia.")
    parceria = Parceria(
        guild_id=guild_id,
        nome_familia=data.nome_familia,
        nome_familia_normalizado=normalize_nome_familia(data.nome_familia),
        produto=data.produto,
        contato_01=data.contato_01,
        contato_02=data.contato_02,
        mensagem_lista_id=data.mensagem_lista_id,
        nome_arquivo_imagem=data.nome_arquivo_imagem,
        registrado_por=data.registrado_por,
    )
    session.add(parceria)
    await session.flush()
    return parceria


async def update_details(session: AsyncSession, parceria_id: int, data: ParceriaUpdateIn) -> Parceria:
    parceria = await get_parceria(session, parceria_id)
    if await name_exists_for_other(session, parceria.guild_id, data.nome_familia, parceria_id):
        raise HTTPException(status_code=409, detail="Ja existe parceria registrada com esse nome de familia.")
    parceria.nome_familia = data.nome_familia
    parceria.nome_familia_normalizado = normalize_nome_familia(data.nome_familia)
    parceria.produto = data.produto
    parceria.contato_01 = data.contato_01
    parceria.contato_02 = data.contato_02
    parceria.updated_at = datetime.now(timezone.utc)
    return parceria


async def update_image(session: AsyncSession, parceria_id: int, nome_arquivo_imagem: str) -> Parceria:
    parceria = await get_parceria(session, parceria_id)
    parceria.nome_arquivo_imagem = nome_arquivo_imagem
    parceria.updated_at = datetime.now(timezone.utc)
    return parceria


async def deactivate(session: AsyncSession, parceria_id: int) -> None:
    parceria = await get_parceria(session, parceria_id)
    parceria.ativo = False
