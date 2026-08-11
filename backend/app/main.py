from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, config, control_plane, farm_tickets, health, internal, licenses, parceria, products, systems, webhooks
from app.api.platform import router as platform_router
from app.core.config import get_settings
from app.db import create_database
from app.platform.registry import discover_domain_modules


settings = get_settings()
discover_domain_modules()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_database()
    yield


app = FastAPI(
    title="Yuno API",
    version="0.1.0",
    description="API central para licencas, configuracoes e sistemas do bot Yuno.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + [settings.public_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(licenses.router)
app.include_router(internal.router)
app.include_router(control_plane.router)
app.include_router(platform_router)
app.include_router(config.router)
app.include_router(farm_tickets.router)
app.include_router(parceria.router)
app.include_router(products.router)
app.include_router(systems.router)
app.include_router(webhooks.router)
