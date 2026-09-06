from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.platform.schemas import ActorContextIn


class BauSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BauConfig(BauSchema):
    enabled: bool = True
    panel_channel_id: str = Field(default="", max_length=32)
    log_channel_id: str = Field(default="", max_length=32)
    staff_role_ids: list[str] = Field(default_factory=list, max_length=10)
    panel_title: str = Field(default="Baú da Gerência", min_length=1, max_length=256)
    panel_description: str = Field(
        default="Controle de estoque compartilhado da organização.",
        min_length=1,
        max_length=4000,
    )
    panel_footer: str = Field(default="Yuno • Baú da Gerência", max_length=2048)
    log_title: str = Field(default="Movimentação no Baú", min_length=1, max_length=256)


class BauMovementItem(BauSchema):
    item_id: str = Field(min_length=1, max_length=36)
    raw: str = Field(default="", max_length=20)


class BauMovementCommand(BauSchema):
    actor: ActorContextIn
    items: list[BauMovementItem] = Field(min_length=1, max_length=5)


class BauCategoryCreateCommand(BauSchema):
    actor: ActorContextIn
    name: str = Field(min_length=1, max_length=60)


class BauCategoryRenameCommand(BauSchema):
    actor: ActorContextIn
    name: str = Field(min_length=1, max_length=60)
    new_name: str = Field(min_length=1, max_length=60)


class BauCategoryRemoveCommand(BauSchema):
    actor: ActorContextIn
    name: str = Field(min_length=1, max_length=60)


class BauItemCreateCommand(BauSchema):
    actor: ActorContextIn
    category_name: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)


class BauItemRenameCommand(BauSchema):
    actor: ActorContextIn
    name: str = Field(min_length=1, max_length=80)
    new_name: str = Field(min_length=1, max_length=80)


class BauItemRemoveCommand(BauSchema):
    actor: ActorContextIn
    name: str = Field(min_length=1, max_length=80)


class BauClearCommand(BauSchema):
    actor: ActorContextIn
    confirm: bool = False
