"""Painel de status dos modulos, publicado dentro do Discord (`/yuno painel`).

Nao e um editor de configuracao: cada modulo ja tem seu proprio comando com
seletor nativo do Discord (`/set painel`, `/meta painel`, etc.), e alguns tem
efeito colateral alem de salvar dado (o `/set painel` tambem tranca
visibilidade de canal). Reimplementar isso de forma generica duplicaria ou
perderia esses efeitos, sem meio de testar contra um Discord real. Em vez
disso, o painel mostra o estado de cada modulo (configurado / incompleto /
desligado) e aponta o comando certo -- resolve o problema real, que e nao ter
um lugar unico pra ver e alcancar cada modulo sem sair do Discord.

Publicado como payload cru de Components V2 (a versao de discord.py deste
projeto nao tem wrapper nativo para isso -- ver `discord.ui.LayoutView` em
versoes mais novas). Segue o mesmo padrao ja provado em produção no Morro do
Mineiro (`cogs/dashboard.py`): tipos de componente por numero, `Section` +
`accessory` para o botao ao lado de cada linha, e uma View "dispatcher" que
nunca e renderizada diretamente -- ela so existe para o discord.py rotear o
clique de um custom_id para o callback certo, porque a mensagem em si foi
enviada via HTTP cru, nao pelo `View.send`.
"""

from __future__ import annotations

from typing import Any, Callable

import discord
import httpx
from discord.ext import commands

from yuno_bot.api_client import YunoAPI
from yuno_bot.modules import DashboardField, ModuleSpec, discover_modules, get_module

_ACTION_ROW = 1
_BUTTON = 2
_SECTION = 9
_TEXT = 10
_SEPARATOR = 14
_CONTAINER = 17
_FLAG_V2 = 1 << 15  # IS_COMPONENTS_V2
# Sete secoes mantem cada payload abaixo de 30 componentes totais, inclusive
# em clientes/rotas que ainda aplicam o limite original de Components V2.
_PAGE_SIZE = 7

_STATUS_BADGE = {"configurado": "✅", "incompleto": "⚠️", "desligado": "⛔"}
_STATUS_LABEL = {"configurado": "Configurado", "incompleto": "Incompleto", "desligado": "Desligado"}
_STATUS_COLOR = {"configurado": 0x2ECC71, "incompleto": 0xF1C40F, "desligado": 0x95A5A6}

# Cada modulo guarda os valores dos seus dashboard_fields num lugar diferente:
# a maioria em settings.<modulo>, populado pelo proprio comando de painel do
# modulo; farm_tickets e parceria tem tabela dedicada no backend mas espelham
# um resumo em settings.<modulo> pelo mesmo motivo (ver app/farm_tickets.py e
# app/parceria.py). Modulos simples usam o canal criado por `/yuno configurar`
# como fallback e passam a salvar a referencia assim que o painel e publicado.
_SIMPLE_MODULES: dict[str, str] = {
    "encomenda": "encomendas",
    "producao": "producao",
    "ticket": "tickets",
    "adv": "adv",
}

_COMMAND_HINTS: dict[str, str] = {
    "set": "/set painel",
    "meta": "/meta painel",
    "ausencia": "/setup_ausencia",
    "radio": "/radio painel",
    "parceria": "/setup_parcerias",
    "farm_tickets": "/setup_farm_tickets",
    "encomenda": "/encomenda painel",
    "producao": "/producao painel",
    "ticket": "/ticket painel",
    "adv": "/adv painel",
    "anuncio": "/anuncio painel",
    "hierarquia": "/hierarquia painel",
    "membros": "/membros configurar",
    "acao": "/acao painel",
    "disparo": "/disparo painel",
}


def _settings_values(config: dict, key: str) -> dict[str, Any]:
    return dict((config.get("settings") or {}).get(key) or {})


def _discord_setup_channel_value(config: dict, setup_key: str) -> dict[str, Any]:
    channel_id = ((config.get("settings") or {}).get("discord_setup") or {}).get("channel_ids") or {}
    valor = channel_id.get(setup_key)
    return {"panel_channel_id": valor} if valor else {}


def module_values(module_key: str, config: dict) -> dict[str, Any]:
    setup_key = _SIMPLE_MODULES.get(module_key)
    if setup_key:
        return {
            **_discord_setup_channel_value(config, setup_key),
            **_settings_values(config, module_key),
        }
    return _settings_values(config, module_key)


def compute_status(spec: ModuleSpec, config: dict) -> str:
    if not (config.get("modules") or {}).get(spec.key, False):
        return "desligado"
    if not spec.dashboard_fields:
        return "configurado"
    values = module_values(spec.key, config)
    for campo in spec.dashboard_fields:
        if campo.obrigatorio and not values.get(campo.key):
            return "incompleto"
    return "configurado"


def _mention(tipo: str, valor: Any) -> str:
    if tipo in ("channel", "category"):
        return f"<#{valor}>"
    if tipo in ("role", "roles"):
        return f"<@&{valor}>"
    return str(valor)


def _format_value(campo: DashboardField, valor: Any) -> str:
    if not valor:
        return "_não definido_"
    if isinstance(valor, list):
        return " ".join(_mention(campo.tipo, item) for item in valor)
    return _mention(campo.tipo, valor)


def module_info_embed(spec: ModuleSpec, config: dict) -> discord.Embed:
    status = compute_status(spec, config)
    values = module_values(spec.key, config)
    embed = discord.Embed(title=f"{spec.icon} {spec.nome}", description=spec.descricao, color=_STATUS_COLOR[status])
    embed.add_field(name="Estado", value=f"{_STATUS_BADGE[status]} {_STATUS_LABEL[status]}", inline=False)
    for campo in spec.dashboard_fields:
        rotulo = campo.label if campo.obrigatorio else f"{campo.label} (opcional)"
        embed.add_field(name=rotulo, value=_format_value(campo, values.get(campo.key)), inline=False)
    if status == "desligado":
        embed.add_field(
            name="Como resolver",
            value="Módulo desligado para este servidor. Ative-o no painel web ou fale com o suporte.",
            inline=False,
        )
    elif status == "incompleto":
        hint = _COMMAND_HINTS.get(spec.key)
        if hint:
            embed.add_field(name="Como resolver", value=f"Rode `{hint}` para completar a configuração.", inline=False)
    return embed


def _page_count() -> int:
    return max(1, (len(discover_modules()) + _PAGE_SIZE - 1) // _PAGE_SIZE)


def build_payload(config: dict, page: int = 0) -> dict[str, Any]:
    specs = list(discover_modules().values())
    pages = _page_count()
    page = max(0, min(page, pages - 1))
    visible_specs = specs[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]
    inner: list[dict[str, Any]] = [
        {
            "type": _TEXT,
            "content": (
                "# Painel do Yuno\n"
                "Estado de cada módulo. Clique em **≡** para configurar, ativar ou ver o que falta.\n"
                f"Página **{page + 1}/{pages}**"
            ),
        },
        {"type": _SEPARATOR, "divider": True, "spacing": 1},
    ]

    for spec in visible_specs:
        status = compute_status(spec, config)
        inner.append(
            {
                "type": _SECTION,
                "components": [
                    {
                        "type": _TEXT,
                        "content": f"{_STATUS_BADGE[status]} {spec.icon} **{spec.nome}**\n{spec.descricao}",
                    }
                ],
                "accessory": {
                    "type": _BUTTON,
                    "label": "≡",
                    "style": 2,
                    "custom_id": f"yuno:painel:info:{spec.key}",
                },
            }
        )

    inner.append({"type": _SEPARATOR, "divider": True, "spacing": 1})
    inner.append(
        {
            "type": _ACTION_ROW,
            "components": [
                {
                    "type": _BUTTON,
                    "label": "← Anterior",
                    "style": 2,
                    "custom_id": f"yuno:painel:page:{page - 1}",
                    "disabled": page == 0,
                },
                {
                    "type": _BUTTON,
                    "label": "Próxima →",
                    "style": 2,
                    "custom_id": f"yuno:painel:page:{page + 1}",
                    "disabled": page >= pages - 1,
                },
            ],
        }
    )
    inner.append({"type": _TEXT, "content": "✅ configurado · ⚠️ incompleto · ⛔ desligado"})

    return {"flags": _FLAG_V2, "components": [{"type": _CONTAINER, "components": inner}]}


async def _send_v2(bot: commands.Bot, channel_id: int, payload: dict) -> int:
    route = discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    data = await bot.http.request(route, json=payload)
    return int(data["id"])


async def _edit_v2(bot: commands.Bot, channel_id: int, message_id: int, payload: dict) -> None:
    route = discord.http.Route(
        "PATCH", "/channels/{channel_id}/messages/{message_id}", channel_id=channel_id, message_id=message_id
    )
    await bot.http.request(route, json=payload)


def dashboard_message_ref(config: dict) -> tuple[int | None, int | None]:
    settings = (config.get("settings") or {}).get("dashboard") or {}
    channel_id = settings.get("panel_channel_id")
    message_id = settings.get("panel_message_id")
    return (int(channel_id) if channel_id else None, int(message_id) if message_id else None)


def with_dashboard_ref(config: dict, *, channel_id: int, message_id: int) -> dict:
    settings = dict(config.get("settings") or {})
    settings["dashboard"] = {"panel_channel_id": str(channel_id), "panel_message_id": str(message_id)}
    return {**config, "settings": settings}


async def publish_or_update(bot: commands.Bot, channel: discord.TextChannel, config: dict) -> int:
    """Publica o painel, ou atualiza a mensagem existente se ainda estiver no mesmo canal."""
    payload = build_payload(config)
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if previous_message_id and previous_channel_id == channel.id:
        try:
            await _edit_v2(bot, channel.id, previous_message_id, payload)
            return previous_message_id
        except discord.HTTPException:
            pass
    return await _send_v2(bot, channel.id, payload)


class PainelDispatcherView(discord.ui.View):
    """Registrada so para roteamento persistente de custom_ids.

    Nunca e renderizada diretamente -- a mensagem do painel usa payload V2 cru
    (`build_payload`). O discord.py roteia o clique pelo `custom_id`, entao
    basta os ids baterem com o que `build_payload` gerou.
    """

    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api
        for spec in discover_modules().values():
            button: discord.ui.Button = discord.ui.Button(
                custom_id=f"yuno:painel:info:{spec.key}",
                style=discord.ButtonStyle.secondary,
                label="≡",
            )
            button.callback = self._make_callback(spec.key)
            self.add_item(button)
        for page in range(_page_count()):
            button = discord.ui.Button(
                custom_id=f"yuno:painel:page:{page}",
                style=discord.ButtonStyle.secondary,
                label=f"Página {page + 1}",
            )
            button.callback = self._make_page_callback(page)
            self.add_item(button)

    def _make_callback(self, module_key: str) -> Callable[[discord.Interaction], Any]:
        async def callback(interaction: discord.Interaction) -> None:
            await show_module_info(interaction, self.api, module_key)

        return callback

    def _make_page_callback(self, page: int) -> Callable[[discord.Interaction], Any]:
        async def callback(interaction: discord.Interaction) -> None:
            if not interaction.guild or not interaction.message or not interaction.channel_id:
                await interaction.response.send_message("Painel indisponível.", ephemeral=True)
                return
            await interaction.response.defer()
            try:
                config = await self.api.get_guild_config(interaction.guild.id)
                await _edit_v2(
                    interaction.client,
                    interaction.channel_id,
                    interaction.message.id,
                    build_payload(config, page),
                )
            except (httpx.HTTPError, discord.HTTPException):
                await interaction.followup.send("Não consegui trocar a página do painel.", ephemeral=True)

        return callback


class ModuleInfoView(discord.ui.View):
    """Controles administrativos exibidos ao abrir um modulo no painel geral."""

    def __init__(self, api: YunoAPI, spec: ModuleSpec, config: dict) -> None:
        super().__init__(timeout=180)
        self.api = api
        self.spec = spec
        enabled = bool((config.get("modules") or {}).get(spec.key, False))
        toggle = discord.ui.Button(
            label="Desativar módulo" if enabled else "Ativar módulo",
            emoji="⏸️" if enabled else "▶️",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            custom_id=f"yuno:painel:toggle:{spec.key}",
        )
        toggle.callback = self.toggle_module
        self.add_item(toggle)

    async def toggle_module(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use dentro de um servidor.", ephemeral=True)
            return
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await interaction.response.send_message(
                "Você precisa ter permissão de gerenciar servidor.", ephemeral=True
            )
            return
        try:
            config = await self.api.get_guild_config(interaction.guild.id, force=True)
            modules = dict(config.get("modules") or {})
            modules[self.spec.key] = not bool(modules.get(self.spec.key, False))
            updated = {
                "guild_name": config.get("guild_name"),
                "admin_role_ids": config.get("admin_role_ids") or [],
                "log_channel_id": config.get("log_channel_id"),
                "modules": modules,
                "command_permissions": config.get("command_permissions") or {},
                "messages": config.get("messages") or {},
                "settings": config.get("settings") or {},
            }
            saved = await self.api.save_guild_config(interaction.guild.id, updated)
        except httpx.HTTPError:
            await interaction.response.send_message("Não consegui salvar a configuração.", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=module_info_embed(self.spec, saved),
            view=ModuleInfoView(self.api, self.spec, saved),
        )


async def show_module_info(interaction: discord.Interaction, api: YunoAPI, module_key: str) -> None:
    spec = get_module(module_key)
    if not spec:
        await interaction.response.send_message("Módulo não encontrado.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
        return
    try:
        config = await api.get_guild_config(interaction.guild.id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            await interaction.response.send_message("Este servidor ainda não possui licença ativa.", ephemeral=True)
            return
        await interaction.response.send_message("Não consegui carregar a configuração do servidor.", ephemeral=True)
        return
    except httpx.HTTPError:
        await interaction.response.send_message("Não consegui falar com a API do Yuno.", ephemeral=True)
        return

    await interaction.response.send_message(
        embed=module_info_embed(spec, config),
        view=ModuleInfoView(api, spec, config),
        ephemeral=True,
    )
