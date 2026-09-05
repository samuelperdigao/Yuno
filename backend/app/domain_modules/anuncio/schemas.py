from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.platform.schemas import ActorContextIn


class AnuncioSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnuncioConfig(AnuncioSchema):
    enabled: bool = True
    channel_id: str = Field(default="", max_length=32)
    log_channel_id: str = Field(default="", max_length=32)
    authorized_role_ids: list[str] = Field(default_factory=list)
    panel_title: str = Field(default="Central de Anúncios", min_length=1, max_length=256)
    panel_description: str = Field(
        default="Publique um novo anúncio oficial para o servidor.",
        min_length=1,
        max_length=4000,
    )
    button_label: str = Field(default="Novo Anúncio", min_length=1, max_length=80)
    button_emoji: str = Field(default="📢", max_length=32)
    panel_footer: str = Field(default="Yuno • Anúncios", max_length=2048)
    log_title: str = Field(default="Novo anúncio publicado", min_length=1, max_length=256)


class AnuncioPublish(AnuncioSchema):
    titulo: str = Field(min_length=1, max_length=256)
    conteudo: str = Field(min_length=1, max_length=4000)
    mencionar_everyone: bool = False
    anexou_arquivo: bool = False


class AnuncioPublishCommand(AnuncioSchema):
    actor: ActorContextIn
    anuncio: AnuncioPublish
