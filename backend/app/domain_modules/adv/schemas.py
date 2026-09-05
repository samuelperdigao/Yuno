from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.platform.schemas import ActorContextIn


class AdvSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AdvConfig(AdvSchema):
    enabled: bool = True
    panel_channel_id: str = Field(default="", max_length=32)
    log_channel_id: str = Field(default="", max_length=32)
    staff_role_ids: list[str] = Field(default_factory=list, max_length=10)
    panel_title: str = Field(default="Sistema de Advertência", min_length=1, max_length=256)
    panel_description: str = Field(
        default="Aplique advertências a membros e mantenha o histórico organizado.",
        min_length=1,
        max_length=4000,
    )
    button_label: str = Field(default="Aplicar Advertência", min_length=1, max_length=80)
    button_emoji: str = Field(default="⚠️", max_length=32)
    panel_footer: str = Field(default="Yuno • Sistema de Advertência", max_length=2048)
    confirmation_message: str = Field(
        default="Advertência aplicada com sucesso.", min_length=1, max_length=2000
    )
    log_title: str = Field(default="Nova advertência aplicada", min_length=1, max_length=256)
    revoke_log_title: str = Field(default="Advertência revogada", min_length=1, max_length=256)


class AdvApply(AdvSchema):
    discord_user_id: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=300)


class AdvApplyCommand(AdvSchema):
    actor: ActorContextIn
    apply: AdvApply
    member_display_name: str = Field(min_length=1, max_length=120)
    moderator_display_name: str = Field(min_length=1, max_length=120)


class AdvRevoke(AdvSchema):
    warning_id: str = Field(min_length=1, max_length=36)
    reason: str | None = Field(default=None, max_length=300)


class AdvRevokeCommand(AdvSchema):
    actor: ActorContextIn
    revoke: AdvRevoke
    actor_display_name: str = Field(min_length=1, max_length=120)
