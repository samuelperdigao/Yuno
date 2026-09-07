from yuno_bot.domain_modules.chest.admin import (
    add_chest,
    add_item,
    audit_log,
    configure,
    diagnose,
    edit_texts,
    inventory,
    link_items,
    manage_chests,
    manage_items,
    open_access,
    publish_catalog,
    recover,
    render_admin,
    set_log_channel,
    set_operator_roles,
    set_panel_channel,
    toggle_balances,
    toggle_history,
    toggle_reason,
)
from yuno_bot.domain_modules.chest.runtime import (
    deliver_log,
    deliver_panel,
    handle_resource_delete,
    run_job,
    startup,
)
from yuno_bot.domain_modules.chest.ui import (
    chests_next,
    chests_prev,
    choose_chest,
    deposit,
    deposit_cancel,
    deposit_confirm,
    deposit_item,
    deposit_next,
    deposit_prev,
    deposit_submit,
    history_own,
    own_history_owner,
    render_global,
    select_chest,
    view_stock,
    withdraw,
    withdraw_cancel,
    withdraw_confirm,
    withdraw_item,
    withdraw_next,
    withdraw_prev,
    withdraw_submit,
)
from yuno_bot.platform.contracts import (
    ActionDefinition,
    AdminActionDefinition,
    AdminPageDefinition,
    DeliveryRendererDefinition,
    JobHandlerDefinition,
    ModuleUIAdapter,
    PanelDefinition,
)

MODULE_UI = ModuleUIAdapter(
    module_key="chest",
    contract_version=1,
    name="Sistema de Bau",
    description="Catalogo versionado, estoque e ledger imutavel.",
    icon="📦",
    order=35,
    minimum_plan="basico",
    admin_pages=(AdminPageDefinition("overview", render_admin),),
    admin_actions=(
        AdminActionDefinition("inventory", inventory),
        AdminActionDefinition("add_chest", add_chest),
        AdminActionDefinition("add_item", add_item),
        AdminActionDefinition("audit", audit_log),
        AdminActionDefinition("link_items", link_items),
        AdminActionDefinition("manage_chests", manage_chests),
        AdminActionDefinition("manage_items", manage_items),
        AdminActionDefinition("access", open_access),
        AdminActionDefinition("configuration", configure),
        AdminActionDefinition("publish", publish_catalog),
        AdminActionDefinition("diagnose", diagnose),
        AdminActionDefinition("recover", recover),
        AdminActionDefinition("set_operator_roles", set_operator_roles),
        AdminActionDefinition("set_panel_channel", set_panel_channel),
        AdminActionDefinition("set_log_channel", set_log_channel),
        AdminActionDefinition("toggle_balances", toggle_balances),
        AdminActionDefinition("toggle_history", toggle_history),
        AdminActionDefinition("toggle_reason", toggle_reason),
        AdminActionDefinition("edit_texts", edit_texts),
    ),
    panels=(
        PanelDefinition(
            "global", render_global, version=1, recovery_policy="automatic"
        ),
    ),
    actions=(
        ActionDefinition(
            "select_chest", "global", "chest.view", select_chest, panel_key="global"
        ),
        ActionDefinition(
            "chests_prev", "global", "chest.view", chests_prev, panel_key="global"
        ),
        ActionDefinition(
            "chests_next", "global", "chest.view", chests_next, panel_key="global"
        ),
        ActionDefinition(
            "choose_chest", "global", "chest.view", choose_chest, panel_key="global"
        ),
        ActionDefinition(
            "view_stock", "global", "chest.view", view_stock, panel_key="global"
        ),
        ActionDefinition(
            "deposit", "global", "chest.deposit", deposit, panel_key="global"
        ),
        ActionDefinition(
            "deposit_prev", "global", "chest.deposit", deposit_prev, panel_key="global"
        ),
        ActionDefinition(
            "deposit_next", "global", "chest.deposit", deposit_next, panel_key="global"
        ),
        ActionDefinition(
            "deposit_item", "global", "chest.deposit", deposit_item, panel_key="global"
        ),
        ActionDefinition(
            "deposit_submit",
            "global",
            "chest.deposit",
            deposit_submit,
            panel_key="global",
        ),
        ActionDefinition(
            "deposit_confirm",
            "global",
            "chest.deposit",
            deposit_confirm,
            panel_key="global",
        ),
        ActionDefinition(
            "deposit_cancel",
            "global",
            "chest.deposit",
            deposit_cancel,
            panel_key="global",
        ),
        ActionDefinition(
            "withdraw", "global", "chest.withdraw", withdraw, panel_key="global"
        ),
        ActionDefinition(
            "withdraw_prev",
            "global",
            "chest.withdraw",
            withdraw_prev,
            panel_key="global",
        ),
        ActionDefinition(
            "withdraw_next",
            "global",
            "chest.withdraw",
            withdraw_next,
            panel_key="global",
        ),
        ActionDefinition(
            "withdraw_item",
            "global",
            "chest.withdraw",
            withdraw_item,
            panel_key="global",
        ),
        ActionDefinition(
            "withdraw_submit",
            "global",
            "chest.withdraw",
            withdraw_submit,
            panel_key="global",
        ),
        ActionDefinition(
            "withdraw_confirm",
            "global",
            "chest.withdraw",
            withdraw_confirm,
            panel_key="global",
        ),
        ActionDefinition(
            "withdraw_cancel",
            "global",
            "chest.withdraw",
            withdraw_cancel,
            panel_key="global",
        ),
        ActionDefinition(
            "history_own",
            "global",
            "chest.history_own",
            history_own,
            panel_key="global",
            resource_owner_resolver=own_history_owner,
        ),
    ),
    jobs=(JobHandlerDefinition("chest.panel.reconcile", run_job),),
    deliveries=(
        DeliveryRendererDefinition("chest.panel", deliver_panel),
        DeliveryRendererDefinition("chest.log", deliver_log),
    ),
    startup_handler=startup,
    resource_delete_handler=handle_resource_delete,
)

__all__ = ["MODULE_UI"]
