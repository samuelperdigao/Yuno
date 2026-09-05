from yuno_bot.domain_modules.log_membros.admin import (
    confirm_publish,
    edit_leave_message,
    open_system,
    overview,
    render_admin,
    review_publish,
    set_join_channel,
    set_join_roles,
    set_leave_channel,
)
from yuno_bot.domain_modules.log_membros.runtime import handle_member_join, handle_member_remove
from yuno_bot.platform.contracts import AdminActionDefinition, AdminPageDefinition, ModuleUIAdapter

MODULE_UI = ModuleUIAdapter(
    module_key="log_membros",
    contract_version=1,
    name="Entrada e Saída de Membros",
    description=(
        "Log automático de entrada e saída, com cargo de boas-vindas configurável "
        "e detecção de expulsão/banimento pelo log de auditoria."
    ),
    icon="👥",
    order=15,
    minimum_plan="basico",
    admin_pages=(AdminPageDefinition("overview", render_admin),),
    admin_actions=(
        AdminActionDefinition("overview", overview),
        AdminActionDefinition("open_system", open_system),
        AdminActionDefinition("set_join_channel", set_join_channel),
        AdminActionDefinition("set_leave_channel", set_leave_channel),
        AdminActionDefinition("set_join_roles", set_join_roles),
        AdminActionDefinition("edit_leave_message", edit_leave_message),
        AdminActionDefinition("review_publish", review_publish),
        AdminActionDefinition("confirm_publish", confirm_publish),
    ),
    member_join_handler=handle_member_join,
    member_remove_handler=handle_member_remove,
)

__all__ = ["MODULE_UI"]
