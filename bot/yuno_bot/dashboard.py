"""Central de Gestão persistente do Yuno dentro do Discord.

Modulos que implementam ``ControlPlaneSpec`` oferecem editor, previa,
publicacao e diagnostico. Os demais continuam com views/listeners carregados,
mas sao identificados honestamente como pendentes de migracao e nunca apontam
para comandos slash legados.

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

from yuno_bot import diagnostics
from yuno_bot.api_client import YunoAPI
from yuno_bot.control_plane import is_control_plane_admin, pending_changes
from yuno_bot.modules import DashboardField, ModuleSpec, discover_modules, get_module

_ACTION_ROW = 1
_BUTTON = 2
_SECTION = 9
_TEXT = 10
_SEPARATOR = 14
_CONTAINER = 17
_FLAG_V2 = 1 << 15  # IS_COMPONENTS_V2
# Seis secoes mantem cada payload abaixo de 30 componentes totais, inclusive
# em clientes/rotas que ainda aplicam o limite original de Components V2.
_PAGE_SIZE = 6

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


def module_info_embed(spec: ModuleSpec, config: dict, state: dict | None = None) -> discord.Embed:
    status = compute_status(spec, config)
    values = module_values(spec.key, config)
    embed = discord.Embed(title=f"{spec.icon} {spec.nome}", description=spec.descricao, color=_STATUS_COLOR[status])
    embed.add_field(name="Estado", value=f"{_STATUS_BADGE[status]} {_STATUS_LABEL[status]}", inline=False)
    for campo in spec.dashboard_fields:
        rotulo = campo.label if campo.obrigatorio else f"{campo.label} (opcional)"
        embed.add_field(name=rotulo, value=_format_value(campo, values.get(campo.key)), inline=False)
    if spec.control_plane is None:
        embed.add_field(
            name="Central de Gestão",
            value="Migração para a Central pendente.",
            inline=False,
        )
    else:
        state = state or {}
        embed.add_field(
            name="Versão publicada",
            value=str(state.get("published_revision", 0) or "Nenhuma"),
            inline=True,
        )
        embed.add_field(
            name="Alterações pendentes",
            value="Sim" if pending_changes(state) else "Não",
            inline=True,
        )
    return embed


def _page_count() -> int:
    return max(1, (len(discover_modules()) + _PAGE_SIZE - 1) // _PAGE_SIZE)


def build_payload(
    config: dict,
    page: int = 0,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
    license_active: bool = True,
) -> dict[str, Any]:
    specs = list(discover_modules().values())
    pages = _page_count()
    page = max(0, min(page, pages - 1))
    visible_specs = specs[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]
    states = control_states or {}
    active_count = sum(bool(value) for value in (config.get("modules") or {}).values())
    inner: list[dict[str, Any]] = [
        {
            "type": _TEXT,
            "content": (
                "# Central de Gestão do Yuno\n"
                f"Licença: **{'ativa' if license_active else 'inativa'}** · Módulos ativos: **{active_count}**\n"
                "Clique em **Abrir** para administrar ou diagnosticar um módulo.\n"
                f"Página **{page + 1}/{pages}**"
            ),
        },
        {"type": _SEPARATOR, "divider": True, "spacing": 1},
    ]

    for spec in visible_specs:
        status = compute_status(spec, config)
        state = states.get(spec.key) or {}
        if spec.control_plane is None:
            detail = "Migração para a Central pendente"
        else:
            version = state.get("published_revision", 0)
            detail = f"Versão publicada: {version or 'nenhuma'} · Alterações pendentes: {'sim' if pending_changes(state) else 'não'}"
        inner.append(
            {
                "type": _SECTION,
                "components": [
                    {
                        "type": _TEXT,
                        "content": f"{_STATUS_BADGE[status]} {spec.icon} **{spec.nome}**\n{spec.descricao}\n_{detail}_",
                    }
                ],
                "accessory": {
                    "type": _BUTTON,
                    "label": "Abrir",
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
                    "label": "Status",
                    "style": 2,
                    "custom_id": "yuno:painel:status",
                },
                {
                    "type": _BUTTON,
                    "label": "Diagnóstico",
                    "style": 2,
                    "custom_id": "yuno:painel:diagnostico",
                },
            ],
        }
    )
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
    try:
        normalized_channel_id = int(channel_id) if channel_id else None
    except (TypeError, ValueError):
        normalized_channel_id = None
    try:
        normalized_message_id = int(message_id) if message_id else None
    except (TypeError, ValueError):
        normalized_message_id = None
    return normalized_channel_id, normalized_message_id


def with_dashboard_ref(config: dict, *, channel_id: int, message_id: int) -> dict:
    settings = dict(config.get("settings") or {})
    settings["dashboard"] = {"panel_channel_id": str(channel_id), "panel_message_id": str(message_id)}
    return {**config, "settings": settings}


async def publish_or_update(
    bot: commands.Bot,
    channel: discord.TextChannel,
    config: dict,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Publica o painel, ou atualiza a mensagem existente se ainda estiver no mesmo canal."""
    payload = build_payload(config, control_states=control_states)
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if previous_message_id and previous_channel_id == channel.id:
        try:
            known_message = await channel.fetch_message(previous_message_id)
            if channel.guild.me and known_message.author.id != channel.guild.me.id:
                return await _send_v2(bot, channel.id, payload)
            await _edit_v2(bot, channel.id, previous_message_id, payload)
            return previous_message_id
        except discord.HTTPException:
            pass
    return await _send_v2(bot, channel.id, payload)


async def rollback_unsaved_dashboard(
    config: dict,
    channel: discord.TextChannel,
    message_id: int,
) -> None:
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if previous_channel_id == channel.id and previous_message_id == message_id:
        return
    try:
        message = await channel.fetch_message(message_id)
        if channel.guild.me and message.author.id == channel.guild.me.id:
            await message.delete()
    except discord.HTTPException:
        pass


async def remove_previous_dashboard(
    config: dict,
    channel: discord.TextChannel,
    message_id: int,
) -> None:
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if not previous_channel_id or not previous_message_id:
        return
    if previous_channel_id == channel.id and previous_message_id == message_id:
        return
    old_channel = channel.guild.get_channel(previous_channel_id)
    if not isinstance(old_channel, discord.TextChannel):
        return
    try:
        message = await old_channel.fetch_message(previous_message_id)
        if channel.guild.me and message.author.id == channel.guild.me.id:
            await message.delete()
    except discord.HTTPException:
        pass


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
        status_button = discord.ui.Button(
            custom_id="yuno:painel:status",
            style=discord.ButtonStyle.secondary,
            label="Status",
        )
        status_button.callback = self._status
        self.add_item(status_button)
        diagnostic_button = discord.ui.Button(
            custom_id="yuno:painel:diagnostico",
            style=discord.ButtonStyle.secondary,
            label="Diagnóstico",
        )
        diagnostic_button.callback = self._diagnostic
        self.add_item(diagnostic_button)
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
                if not isinstance(interaction.user, discord.Member) or not is_control_plane_admin(
                    interaction.guild, interaction.user, config
                ):
                    await interaction.followup.send(
                        "Você não possui permissão para administrar a Central.", ephemeral=True
                    )
                    return
                states = await fetch_control_states(self.api, interaction.guild.id, interaction.user.id)
                await _edit_v2(
                    interaction.client,
                    interaction.channel_id,
                    interaction.message.id,
                    build_payload(config, page, control_states=states),
                )
            except (httpx.HTTPError, discord.HTTPException):
                await interaction.followup.send("Não consegui trocar a página do painel.", ephemeral=True)

        return callback

    async def _status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use dentro de um servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            license_data = await self.api.validate_license(interaction.guild.id)
            config = (
                await self.api.get_guild_config(interaction.guild.id)
                if license_data.get("allowed")
                else {}
            )
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui consultar a licença.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not is_control_plane_admin(
            interaction.guild, interaction.user, config
        ):
            await interaction.followup.send(
                "Você não possui permissão para administrar a Central.", ephemeral=True
            )
            return
        status_text = "ativa" if license_data.get("allowed") else "inativa"
        await interaction.followup.send(f"Licença {status_text}.", ephemeral=True)

    async def _diagnostic(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use dentro de um servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            license_data = await self.api.validate_license(interaction.guild.id)
            config = (
                await self.api.get_guild_config(interaction.guild.id, force=True)
                if license_data.get("allowed")
                else {}
            )
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui executar o diagnóstico.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not is_control_plane_admin(
            interaction.guild, interaction.user, config
        ):
            await interaction.followup.send(
                "Você não possui permissão para administrar a Central.", ephemeral=True
            )
            return
        report = diagnostics.diagnose(
            interaction.guild, config, licenca_ativa=bool(license_data.get("allowed"))
        )
        await interaction.followup.send(
            embed=diagnostics.diagnostic_embed(report, interaction.guild.name), ephemeral=True
        )


class ModuleInfoView(discord.ui.View):
    """Controles administrativos exibidos ao abrir um modulo no painel geral."""

    def __init__(
        self,
        api: YunoAPI,
        spec: ModuleSpec,
        config: dict,
        state: dict | None = None,
        *,
        user_id: int | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.api = api
        self.spec = spec
        self.state = state or {}
        self.user_id = user_id
        enabled = bool((config.get("modules") or {}).get(spec.key, False))
        toggle = discord.ui.Button(
            label="Desativar módulo" if enabled else "Ativar módulo",
            emoji="⏸️" if enabled else "▶️",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            custom_id=f"yuno:painel:toggle:{spec.key}",
        )
        toggle.callback = self.toggle_module
        self.add_item(toggle)
        if spec.control_plane is not None:
            for label, emoji, callback in (
                ("Configurar", "⚙️", self.configure),
                ("Prévia", "🔎", self.preview),
                ("Publicar", "🚀", self.publish),
            ):
                button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)
                button.callback = callback
                self.add_item(button)
        diagnose_button = discord.ui.Button(label="Diagnóstico", emoji="🩺", style=discord.ButtonStyle.secondary)
        diagnose_button.callback = self.diagnose
        self.add_item(diagnose_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.user_id is None or interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Esta sessão administrativa pertence a outro usuário.", ephemeral=True
        )
        return False

    async def _load(self, interaction: discord.Interaction) -> tuple[dict, dict] | None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use dentro de um servidor.", ephemeral=True)
            return None
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            config = await self.api.get_guild_config(interaction.guild.id, force=True)
            if not is_control_plane_admin(interaction.guild, interaction.user, config):
                await interaction.followup.send(
                    "Você não possui permissão para administrar a Central.", ephemeral=True
                )
                return None
            state = self.state
            if self.spec.control_plane is not None:
                state = await self.api.get_module_config_state(
                    interaction.guild.id, self.spec.key, actor_id=interaction.user.id
                )
            return config, state
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send(
                    "Este servidor não possui licença ativa.", ephemeral=True
                )
                return None
            await interaction.followup.send("Não consegui carregar o módulo.", ephemeral=True)
            return None
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui carregar o módulo.", ephemeral=True)
            return None

    async def configure(self, interaction: discord.Interaction) -> None:
        loaded = await self._load(interaction)
        if loaded and self.spec.control_plane:
            await self.spec.control_plane.build_editor(interaction, self.api, loaded[1], loaded[0])

    async def preview(self, interaction: discord.Interaction) -> None:
        loaded = await self._load(interaction)
        if loaded and self.spec.control_plane:
            await self.spec.control_plane.build_preview(interaction, self.api, loaded[1], loaded[0])

    async def publish(self, interaction: discord.Interaction) -> None:
        loaded = await self._load(interaction)
        if loaded and self.spec.control_plane:
            await self.spec.control_plane.publish_panel(interaction, self.api, loaded[1], loaded[0])

    async def diagnose(self, interaction: discord.Interaction) -> None:
        loaded = await self._load(interaction)
        if not loaded:
            return
        if self.spec.control_plane is None:
            text = "⚠️ Migração para a Central pendente. Views e listeners existentes continuam ativos."
            await interaction.followup.send(text, ephemeral=True)
        else:
            await self.spec.control_plane.diagnose(interaction, self.api, loaded[1], loaded[0])

    async def toggle_module(self, interaction: discord.Interaction) -> None:
        loaded = await self._load(interaction)
        if not loaded:
            return
        config, state = loaded
        try:
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
            saved = await self.api.save_guild_config(
                interaction.guild.id, updated, actor_id=interaction.user.id
            )
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui salvar a configuração.", ephemeral=True)
            return

        await interaction.edit_original_response(
            embed=module_info_embed(self.spec, saved, state),
            view=ModuleInfoView(self.api, self.spec, saved, state, user_id=self.user_id),
        )


async def show_module_info(interaction: discord.Interaction, api: YunoAPI, module_key: str) -> None:
    spec = get_module(module_key)
    if not spec:
        await interaction.response.send_message("Módulo não encontrado.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        config = await api.get_guild_config(interaction.guild.id)
        if not isinstance(interaction.user, discord.Member) or not is_control_plane_admin(
            interaction.guild, interaction.user, config
        ):
            await interaction.followup.send(
                "Você não possui permissão para administrar a Central.", ephemeral=True
            )
            return
        state = None
        if spec.control_plane is not None:
            state = await api.get_module_config_state(
                interaction.guild.id, spec.key, actor_id=interaction.user.id
            )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            await interaction.followup.send("Este servidor ainda não possui licença ativa.", ephemeral=True)
            return
        await interaction.followup.send("Não consegui carregar a configuração do servidor.", ephemeral=True)
        return
    except httpx.HTTPError:
        await interaction.followup.send("Não consegui falar com a API do Yuno.", ephemeral=True)
        return

    await interaction.followup.send(
        embed=module_info_embed(spec, config, state),
        view=ModuleInfoView(api, spec, config, state, user_id=interaction.user.id),
        ephemeral=True,
    )


async def fetch_control_states(
    api: YunoAPI,
    guild_id: int,
    actor_id: int,
) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for spec in discover_modules().values():
        if spec.control_plane is None:
            continue
        try:
            states[spec.key] = await api.get_module_config_state(
                guild_id, spec.key, actor_id=actor_id
            )
        except httpx.HTTPError:
            continue
    return states
