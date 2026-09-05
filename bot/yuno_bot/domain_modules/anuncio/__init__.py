from yuno_bot.domain_modules.anuncio.ui import (
    confirm_publish,
    open_form,
    open_system,
    overview,
    render_admin,
    render_public,
    review_publish,
    run_job,
    set_authorized_roles,
    set_channel,
    set_log_channel,
    submit,
)
from yuno_bot.platform.contracts import (
    ActionDefinition,
    AdminActionDefinition,
    AdminPageDefinition,
    JobHandlerDefinition,
    ModuleUIAdapter,
    PanelDefinition,
)

MODULE_UI = ModuleUIAdapter(
    module_key="anuncio",
    contract_version=1,
    name="Sistema de Anúncio",
    description=(
        "Painel fixo para publicar anúncios oficiais no canal do servidor, "
        "com aviso automático no canal de log."
    ),
    icon="📢",
    order=65,
    minimum_plan="basico",
    admin_pages=(AdminPageDefinition("overview", render_admin),),
    admin_actions=(
        AdminActionDefinition("overview", overview),
        AdminActionDefinition("open_system", open_system),
        AdminActionDefinition("set_channel", set_channel),
        AdminActionDefinition("set_log_channel", set_log_channel),
        AdminActionDefinition("set_authorized_roles", set_authorized_roles),
        AdminActionDefinition("review_publish", review_publish),
        AdminActionDefinition("confirm_publish", confirm_publish),
    ),
    panels=(PanelDefinition("public", render_public, recovery_policy="automatic"),),
    actions=(
        ActionDefinition("open_form", "public", "anuncio.publish", open_form, panel_key="public"),
        ActionDefinition("submit", "public", "anuncio.publish", submit, panel_key="public"),
    ),
    jobs=(JobHandlerDefinition("anuncio.panel.reconcile", run_job),),
)

__all__ = ["MODULE_UI"]
