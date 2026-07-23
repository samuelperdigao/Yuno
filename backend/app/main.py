from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, config, health, internal, licenses, products, systems, webhooks
from app.core.config import get_settings
from app.db import create_database


settings = get_settings()


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
app.include_router(config.router)
app.include_router(products.router)
app.include_router(systems.router)
app.include_router(webhooks.router)
