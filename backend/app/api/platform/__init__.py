from fastapi import APIRouter

from app.api.platform import (
    audits,
    automation,
    ausencia,
    configuration,
    deliveries,
    diagnostics,
    farm_tickets,
    interactions,
    meta,
    migrations,
    modules,
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
    deliveries.router,
    interactions.router,
    migrations.router,
    diagnostics.router,
    meta.router,
    farm_tickets.router,
    registration.router,
    tags.router,
    ausencia.router,
    audits.router,
):
    router.include_router(child)
