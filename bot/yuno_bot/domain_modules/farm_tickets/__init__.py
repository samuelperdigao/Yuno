from yuno_bot.domain_modules.farm_tickets.runtime import (
    deliver_event,
    deliver_log,
    deliver_panel,
    deliver_proof_copy,
    handle_message,
    handle_resource_delete,
    run_job,
    startup,
)
from yuno_bot.domain_modules.farm_tickets.ui import (
    approve,
    assign,
    create_entry,
    delete_ticket_global,
    edit_entry,
    finalize,
    list_proofs,
    open_for_member,
    open_ticket,
    proofs_next,
    proofs_previous,
    render_global,
    render_ticket,
    ticket_owner,
    withdraw,
)
from yuno_bot.platform.contracts import (
    ActionDefinition,
    DeliveryRendererDefinition,
    JobHandlerDefinition,
    ModuleUIAdapter,
    PanelDefinition,
)

MODULE_UI = ModuleUIAdapter(
    module_key="farm_tickets",
    contract_version=2,
    name="Tickets de Farm",
    description="Entregas comprovadas e recolhimentos vinculados às Metas.",
    icon="🎫",
    order=25,
    minimum_plan="pro",
    panels=(
        PanelDefinition(
            "global", render_global, version=2, recovery_policy="automatic"
        ),
        PanelDefinition(
            "ticket", render_ticket, version=2, recovery_policy="automatic"
        ),
    ),
    actions=(
        ActionDefinition(
            "open_ticket",
            "global",
            "farm_tickets.open_own",
            open_ticket,
            panel_key="global",
        ),
        ActionDefinition(
            "open_for_member",
            "global",
            "farm_tickets.open_for_member",
            open_for_member,
            panel_key="global",
        ),
        ActionDefinition(
            "delete_ticket_global",
            "global",
            "farm_tickets.delete",
            delete_ticket_global,
            panel_key="global",
        ),
        ActionDefinition(
            "create_entry",
            "ticket",
            "farm_tickets.submit",
            create_entry,
            panel_key="ticket",
            resource_owner_resolver=ticket_owner,
        ),
        ActionDefinition(
            "edit_entry",
            "ticket",
            "farm_tickets.edit",
            edit_entry,
            panel_key="ticket",
            resource_owner_resolver=ticket_owner,
        ),
        ActionDefinition(
            "list_proofs",
            "ticket",
            "farm_tickets.read_proofs",
            list_proofs,
            panel_key="ticket",
            resource_owner_resolver=ticket_owner,
        ),
        ActionDefinition(
            "proofs_previous",
            "ticket",
            "farm_tickets.read_proofs",
            proofs_previous,
            panel_key="ticket",
            resource_owner_resolver=ticket_owner,
        ),
        ActionDefinition(
            "proofs_next",
            "ticket",
            "farm_tickets.read_proofs",
            proofs_next,
            panel_key="ticket",
            resource_owner_resolver=ticket_owner,
        ),
        ActionDefinition(
            "withdraw", "ticket", "farm_tickets.withdraw", withdraw, panel_key="ticket"
        ),
        ActionDefinition(
            "assign", "ticket", "farm_tickets.assign", assign, panel_key="ticket"
        ),
        ActionDefinition(
            "approve", "ticket", "farm_tickets.approve", approve, panel_key="ticket"
        ),
        ActionDefinition(
            "finalize", "ticket", "farm_tickets.finalize", finalize, panel_key="ticket"
        ),
    ),
    jobs=tuple(
        JobHandlerDefinition(key, run_job)
        for key in (
            "farm_tickets.provision",
            "farm_tickets.proof.process",
            "farm_tickets.operation.expire",
            "farm_tickets.meta.consume",
            "farm_tickets.reconcile",
            "farm_tickets.storage.cleanup",
        )
    ),
    deliveries=(
        DeliveryRendererDefinition("farm_tickets.panel", deliver_panel),
        DeliveryRendererDefinition("farm_tickets.log", deliver_log),
        DeliveryRendererDefinition("farm_tickets.proof_copy", deliver_proof_copy),
        DeliveryRendererDefinition("farm_tickets.event", deliver_event),
    ),
    message_handler=handle_message,
    resource_delete_handler=handle_resource_delete,
    startup_handler=startup,
)


__all__ = ["MODULE_UI"]
