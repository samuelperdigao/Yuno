from fastapi import APIRouter

from app.api.platform import (
    automation,
    audits,
    configuration,
    deliveries,
    diagnostics,
    farm,
    interactions,
    migrations,
    modules,
    panels,
    permissions,
    tenancy,
)


router = APIRouter(prefix="/internal/platform", tags=["yuno-platform"])
for child in (
    modules.router,
    tenancy.router,
    configuration.router,
    permissions.router,
    panels.router,
    automation.router,
    deliveries.router,
    interactions.router,
    migrations.router,
    diagnostics.router,
    farm.router,
    audits.router,
):
    router.include_router(child)
