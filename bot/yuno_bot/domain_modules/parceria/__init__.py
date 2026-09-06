from yuno_bot.domain_modules.parceria.admin import (
    build_admin_payload, confirm_publish, diagnose, open_system, recover_panel,
    render_admin, review_publish, set_ativas_channel, set_category,
    set_log_channel, set_manager_roles, set_registrar_channel,
)
from yuno_bot.domain_modules.parceria.runtime import (
    deliver_log, deliver_panel, deliver_publication, handle_message,
    handle_resource_delete, run_job, startup,
)
from yuno_bot.domain_modules.parceria.ui import (
    deactivate, deactivate_cancel, deactivate_confirm, deactivate_select,
    edit, edit_select, edit_submit, register, render_global,
    submit_registration,
)
from yuno_bot.platform.contracts import (
    ActionDefinition, AdminActionDefinition, AdminPageDefinition,
    DeliveryRendererDefinition, JobHandlerDefinition, ModuleUIAdapter,
    PanelDefinition,
)


MODULE_UI = ModuleUIAdapter(
    module_key="parceria",
    contract_version=2,
    name="Parcerias",
    description="Cadastro e publicação de parcerias por guild.",
    icon="🤝",
    order=40,
    minimum_plan="basico",
    admin_pages=(AdminPageDefinition("overview", render_admin),),
    admin_actions=(
        AdminActionDefinition("open_system", open_system),
        AdminActionDefinition("set_registrar_channel", set_registrar_channel),
        AdminActionDefinition("set_ativas_channel", set_ativas_channel),
        AdminActionDefinition("set_manager_roles", set_manager_roles),
        AdminActionDefinition("set_category", set_category),
        AdminActionDefinition("set_log_channel", set_log_channel),
        AdminActionDefinition("review_publish", review_publish),
        AdminActionDefinition("confirm_publish", confirm_publish),
        AdminActionDefinition("diagnose", diagnose),
        AdminActionDefinition("recover_panel", recover_panel),
    ),
    panels=(PanelDefinition("global", render_global, version=1, recovery_policy="automatic"),),
    actions=(
        ActionDefinition("register", "global", "parceria.register", register, panel_key="global"),
        ActionDefinition("submit_registration", "global", "parceria.register", submit_registration, panel_key="global"),
        ActionDefinition("edit", "global", "parceria.edit", edit, panel_key="global"),
        ActionDefinition("edit_select", "global", "parceria.edit", edit_select, panel_key="global"),
        ActionDefinition("edit_submit", "global", "parceria.edit", edit_submit, panel_key="global"),
        ActionDefinition("deactivate", "global", "parceria.deactivate", deactivate, panel_key="global"),
        ActionDefinition("deactivate_select", "global", "parceria.deactivate", deactivate_select, panel_key="global"),
        ActionDefinition("deactivate_confirm", "global", "parceria.deactivate", deactivate_confirm, panel_key="global"),
        ActionDefinition("deactivate_cancel", "global", "parceria.deactivate", deactivate_cancel, panel_key="global"),
    ),
    jobs=tuple(JobHandlerDefinition(key, run_job) for key in ("parceria.registration.expire", "parceria.panel.reconcile", "parceria.publication.reconcile", "parceria.publication.retry")),
    deliveries=(
        DeliveryRendererDefinition("parceria.publication", deliver_publication),
        DeliveryRendererDefinition("parceria.panel", deliver_panel),
        DeliveryRendererDefinition("parceria.log", deliver_log),
    ),
    message_handler=handle_message,
    resource_delete_handler=handle_resource_delete,
    startup_handler=startup,
)

__all__ = ["MODULE_UI"]
