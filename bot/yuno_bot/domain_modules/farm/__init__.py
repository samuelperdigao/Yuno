from yuno_bot.domain_modules.farm.ui import (
    deliver_audit,
    deliver_review_pending,
    open_for_member,
    open_own_ticket,
    render_admin,
    render_public,
    render_review,
    render_ticket,
    review_queue,
    run_job,
    submit_own,
    ticket_progress,
    view_own,
    _ticket_owner,
)
from yuno_bot.platform.contracts import (
    ActionDefinition,
    AdminPageDefinition,
    DeliveryRendererDefinition,
    JobHandlerDefinition,
    ModuleUIAdapter,
    PanelDefinition,
)


MODULE_UI = ModuleUIAdapter(
    module_key="farm",
    contract_version=1,
    name="Farm",
    description="Ciclos, tickets, entregas, comprovantes e revisoes.",
    icon="🌾",
    order=24,
    minimum_plan="pro",
    admin_pages=(AdminPageDefinition("overview", render_admin),),
    panels=(
        PanelDefinition("public", render_public, recovery_policy="automatic"),
        PanelDefinition("ticket", render_ticket, recovery_policy="automatic"),
        PanelDefinition("review", render_review, recovery_policy="automatic"),
    ),
    actions=(
        ActionDefinition("open_own_ticket", "public", "farm.open_own_ticket", open_own_ticket, panel_key="public"),
        ActionDefinition("view_own", "public", "farm.open_own_ticket", view_own, panel_key="public"),
        ActionDefinition("open_for_member", "public", "farm.open_ticket_for_member", open_for_member, panel_key="public"),
        ActionDefinition("submit_own", "ticket", "farm.submit_own", submit_own, panel_key="ticket", resource_owner_resolver=_ticket_owner),
        ActionDefinition("progress", "ticket", "farm.submit_own", ticket_progress, panel_key="ticket", resource_owner_resolver=_ticket_owner),
        ActionDefinition("review_queue", "review", "farm.review", review_queue, panel_key="review"),
    ),
    jobs=tuple(JobHandlerDefinition(key, run_job) for key in ("farm.cycle.start", "farm.cycle.begin_closing", "farm.cycle.finish_closing", "farm.panel.reconcile")),
    deliveries=(
        DeliveryRendererDefinition("farm.audit", deliver_audit),
        DeliveryRendererDefinition("farm.review_pending", deliver_review_pending),
    ),
)
