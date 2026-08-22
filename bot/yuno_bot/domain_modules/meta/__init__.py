from yuno_bot.domain_modules.meta.ui import (
    add_roles,
    confirm_roles,
    create_goal,
    edit_goal,
    edit_name,
    edit_notice,
    edit_objectives,
    edit_schedule,
    render_admin,
    run_job,
    save_settings,
    select_goal,
    set_participation,
    set_recurrence,
    set_type,
    settings,
    submit_goal,
)
from yuno_bot.platform.contracts import (
    AdminActionDefinition,
    AdminPageDefinition,
    JobHandlerDefinition,
    ModuleUIAdapter,
)


MODULE_UI = ModuleUIAdapter(
    module_key="meta",
    contract_version=2,
    name="Sistema de Metas",
    description="Metas recorrentes e personalizadas por todos ou cargos.",
    icon="🎯",
    order=30,
    minimum_plan="basico",
    admin_pages=(AdminPageDefinition("overview", render_admin),),
    admin_actions=tuple(
        AdminActionDefinition(key, handler)
        for key, handler in (
            ("create_goal", create_goal),
            ("settings", settings),
            ("save_settings", save_settings),
            ("select_goal", select_goal),
            ("edit_goal", edit_goal),
            ("edit_name", edit_name),
            ("set_recurrence", set_recurrence),
            ("edit_schedule", edit_schedule),
            ("set_participation", set_participation),
            ("add_roles", add_roles),
            ("confirm_roles", confirm_roles),
            ("set_type", set_type),
            ("edit_objectives", edit_objectives),
            ("edit_notice", edit_notice),
            ("submit_goal", submit_goal),
        )
    ),
    jobs=tuple(
        JobHandlerDefinition(key, run_job)
        for key in (
            "meta.goal.launch",
            "meta.cycle.transition",
            "meta.notice.reconcile",
            "meta.recovery",
        )
    ),
)
