from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.platform.schemas import ActorContextIn


class AusenciaSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AusenciaConfig(AusenciaSchema):
    enabled: bool = True
    panel_channel_id: str = Field(default="", max_length=32)
    log_channel_id: str = Field(default="", max_length=32)
    max_dias: int = Field(default=7, ge=1, le=30)
    panel_title: str = Field(default="Sistema de Ausência", min_length=1, max_length=256)
    panel_description: str = Field(
        default="Vai ficar fora do RP por alguns dias? Registre sua ausência aqui.",
        min_length=1,
        max_length=4000,
    )
    button_label: str = Field(default="Registrar Ausência", min_length=1, max_length=80)
    button_emoji: str = Field(default="📋", max_length=32)
    panel_footer: str = Field(default="Yuno • Sistema de Ausência", max_length=2048)
    confirmation_message: str = Field(
        default="Ausência registrada com sucesso.", min_length=1, max_length=2000
    )
    log_title: str = Field(default="Nova ausência registrada", min_length=1, max_length=256)
    overdue_reminder_title: str = Field(
        default="Sua ausência venceu", min_length=1, max_length=256
    )
    overdue_reminder_message: str = Field(
        default=(
            "Sua ausência chegou ao fim. Renove pelo painel se ainda precisar "
            "ficar fora — mais de 7 dias sem renovar resulta em PD automático."
        ),
        min_length=1,
        max_length=2000,
    )


class AusenciaRegister(AusenciaSchema):
    dias: int = Field(ge=1, le=365)
    motivo: str | None = Field(default=None, max_length=300)


class AusenciaRegisterCommand(AusenciaSchema):
    actor: ActorContextIn
    registro: AusenciaRegister
    member_display_name: str = Field(min_length=1, max_length=120)


class AusenciaSweepCommand(AusenciaSchema):
    actor: ActorContextIn
