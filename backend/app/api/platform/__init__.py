from fastapi import APIRouter

from app.api.platform import (
    audits,
    automation,
    chest,
    configuration,
    deliveries,
    diagnostics,
    farm_tickets,
    interactions,
    meta,
    migrations,
    modules,
    parceria,
    panels,
    permissions,
    registration,
    tags,
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
    chest.router,
    deliveries.router,
    interactions.router,
    migrations.router,
    diagnostics.router,
    meta.router,
    parceria.router,
    farm_tickets.router,
    registration.router,
    tags.router,
    audits.router,
):
    router.include_router(child)
