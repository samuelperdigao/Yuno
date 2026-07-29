from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_bot_token
from app.db import get_session
from app.models import Parceria, ParceriaConfig
from app.parceria import (
    create_parceria,
    deactivate,
    find_by_name,
    get_config,
    get_parceria,
    list_active,
    name_exists_for_other,
    update_details,
    update_image,
    upsert_config,
)
from app.schemas import (
    ParceriaConfigIn,
    ParceriaConfigOut,
    ParceriaCreateIn,
    ParceriaImagePatch,
    ParceriaOut,
    ParceriaUpdateIn,
)
from app.services import active_license_for_guild

router = APIRouter(prefix="/internal/parcerias", tags=["parcerias"], dependencies=[Depends(require_bot_token)])


async def assert_license(session: AsyncSession, guild_id: str) -> None:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")


def config_out(config: ParceriaConfig) -> ParceriaConfigOut:
    return ParceriaConfigOut(
        guild_id=config.guild_id,
        category_id=config.category_id,
        registrar_channel_id=config.registrar_channel_id,
        ativas_channel_id=config.ativas_channel_id,
        panel_message_id=config.panel_message_id,
    )


def parceria_out(parceria: Parceria) -> ParceriaOut:
    return ParceriaOut(
        id=parceria.id,
        guild_id=parceria.guild_id,
        nome_familia=parceria.nome_familia,
        produto=parceria.produto,
        contato_01=parceria.contato_01,
        contato_02=parceria.contato_02,
        mensagem_lista_id=parceria.mensagem_lista_id,
        nome_arquivo_imagem=parceria.nome_arquivo_imagem,
        registrado_por=parceria.registrado_por,
        ativo=parceria.ativo,
        criado_em=parceria.created_at,
        atualizado_em=parceria.updated_at,
    )


@router.get("/guilds/{guild_id}/config", response_model=ParceriaConfigOut | None)
async def read_config(guild_id: str, session: AsyncSession = Depends(get_session)) -> ParceriaConfigOut | None:
    await assert_license(session, guild_id)
    config = await get_config(session, guild_id)
    return config_out(config) if config else None


@router.put("/guilds/{guild_id}/config", response_model=ParceriaConfigOut)
async def save_config(guild_id: str, data: ParceriaConfigIn, session: AsyncSession = Depends(get_session)) -> ParceriaConfigOut:
    await assert_license(session, guild_id)
    config = await upsert_config(session, guild_id, data)
    await session.commit()
    return config_out(config)


@router.get("/guilds/{guild_id}/active", response_model=list[ParceriaOut])
async def read_active(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[ParceriaOut]:
    await assert_license(session, guild_id)
    return [parceria_out(parceria) for parceria in await list_active(session, guild_id)]


@router.get("/guilds/{guild_id}/by-name", response_model=ParceriaOut | None)
async def read_by_name(guild_id: str, nome_familia: str, session: AsyncSession = Depends(get_session)) -> ParceriaOut | None:
    await assert_license(session, guild_id)
    parceria = await find_by_name(session, guild_id, nome_familia)
    return parceria_out(parceria) if parceria else None


@router.get("/guilds/{guild_id}/name-exists")
async def read_name_exists(guild_id: str, nome_familia: str, exclude_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    await assert_license(session, guild_id)
    return {"exists": await name_exists_for_other(session, guild_id, nome_familia, exclude_id)}


@router.post("/guilds/{guild_id}", response_model=ParceriaOut)
async def create(guild_id: str, data: ParceriaCreateIn, session: AsyncSession = Depends(get_session)) -> ParceriaOut:
    await assert_license(session, guild_id)
    parceria = await create_parceria(session, guild_id, data)
    await session.commit()
    return parceria_out(parceria)


@router.get("/{parceria_id}", response_model=ParceriaOut | None)
async def read(parceria_id: int, session: AsyncSession = Depends(get_session)) -> ParceriaOut | None:
    parceria = await session.get(Parceria, parceria_id)
    if not parceria:
        return None
    await assert_license(session, parceria.guild_id)
    return parceria_out(parceria)


@router.patch("/{parceria_id}", response_model=ParceriaOut)
async def update(parceria_id: int, data: ParceriaUpdateIn, session: AsyncSession = Depends(get_session)) -> ParceriaOut:
    parceria = await get_parceria(session, parceria_id)
    await assert_license(session, parceria.guild_id)
    parceria = await update_details(session, parceria_id, data)
    await session.commit()
    return parceria_out(parceria)


@router.patch("/{parceria_id}/imagem", response_model=ParceriaOut)
async def update_imagem(parceria_id: int, data: ParceriaImagePatch, session: AsyncSession = Depends(get_session)) -> ParceriaOut:
    parceria = await get_parceria(session, parceria_id)
    await assert_license(session, parceria.guild_id)
    parceria = await update_image(session, parceria_id, data.nome_arquivo_imagem)
    await session.commit()
    return parceria_out(parceria)


@router.post("/{parceria_id}/desativar")
async def deactivate_parceria(parceria_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    parceria = await get_parceria(session, parceria_id)
    await assert_license(session, parceria.guild_id)
    await deactivate(session, parceria_id)
    await session.commit()
    return {"ok": True}
