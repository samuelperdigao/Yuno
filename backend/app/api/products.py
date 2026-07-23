from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_token
from app.db import get_session
from app.models import Product
from app.schemas import ProductIn, ProductOut
from app.services import audit

router = APIRouter(prefix="/guilds/{guild_id}/products", tags=["products"], dependencies=[Depends(require_admin_token)])


@router.get("", response_model=list[ProductOut])
async def list_products(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[ProductOut]:
    result = await session.execute(select(Product).where(Product.guild_id == guild_id).order_by(Product.name))
    return [ProductOut(id=item.id, guild_id=item.guild_id, name=item.name, unit=item.unit, active=item.active) for item in result.scalars()]


@router.post("", response_model=ProductOut)
async def create_product(guild_id: str, data: ProductIn, session: AsyncSession = Depends(get_session)) -> ProductOut:
    product = Product(guild_id=guild_id, name=data.name, unit=data.unit, active=data.active)
    session.add(product)
    await session.flush()
    await audit(session, action="product.created", entity_type="product", entity_id=str(product.id), guild_id=guild_id, payload=data.model_dump())
    await session.commit()
    return ProductOut(id=product.id, guild_id=product.guild_id, name=product.name, unit=product.unit, active=product.active)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(guild_id: str, product_id: int, data: ProductIn, session: AsyncSession = Depends(get_session)) -> ProductOut:
    product = await session.get(Product, product_id)
    if not product or product.guild_id != guild_id:
        raise HTTPException(status_code=404, detail="Produto nao encontrado.")
    product.name = data.name
    product.unit = data.unit
    product.active = data.active
    await audit(session, action="product.updated", entity_type="product", entity_id=str(product.id), guild_id=guild_id, payload=data.model_dump())
    await session.commit()
    return ProductOut(id=product.id, guild_id=product.guild_id, name=product.name, unit=product.unit, active=product.active)
