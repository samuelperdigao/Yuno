from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.platform.components_v2 import action_row, button, container, edit_message, payload, separator, text_display
from yuno_bot.platform.contracts import ActorContext, RetryableJobError


COLOR = 0xFFC72C
log = logging.getLogger("yuno.tags")
_pages: dict[tuple[int, int], int] = {}


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    permissions = tuple(
        name for name, enabled in (member.guild_permissions if member else []) if enabled
    )
    return ActorContext(
        guild_id=int(interaction.guild_id or 0),
        user_id=interaction.user.id,
        role_ids=tuple(role.id for role in member.roles) if member else (),
        discord_permissions=permissions,
        channel_id=interaction.channel_id,
        category_id=getattr(getattr(interaction.channel, "category", None), "id", None),
        actor_type="user",
        is_guild_owner=bool(interaction.guild and interaction.guild.owner_id == interaction.user.id),
        correlation_id=str(interaction.id),
    )


def system_actor(bot: discord.Client, guild_id: int, correlation_id: str) -> ActorContext:
    if bot.user is None:
        raise RuntimeError("Identidade do bot indisponivel.")
    return ActorContext(
        guild_id=guild_id,
        user_id=bot.user.id,
        role_ids=(),
        discord_permissions=(),
        channel_id=None,
        category_id=None,
        actor_type="system",
        is_guild_owner=False,
        correlation_id=correlation_id,
    )


def _error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
            if isinstance(detail, dict):
                return str(detail.get("detail") or detail)
            if detail:
                return str(detail)
        except Exception:
            pass
    return "Nao foi possivel concluir a acao de Tags. Reabra o modulo e tente novamente."


async def _reply(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _replace(
    interaction: discord.Interaction,
    data: dict,
    *,
    channel_id: int | None = None,
    message_id: int | None = None,
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    target_channel = channel_id or interaction.channel_id
    target_message = message_id or getattr(interaction.message, "id", None)
    if target_channel is None or target_message is None:
        raise RuntimeError("Referencia da Central indisponivel.")
    await edit_message(interaction.client, target_channel, target_message, data)


def _sort_bindings(guild: discord.Guild, bindings: list[dict]) -> list[tuple[dict, discord.Role | None]]:
    roles = {str(role.id): role for role in guild.roles}
    present = [(item, roles.get(str(item["discord_role_id"]))) for item in bindings]
    return sorted(
        present,
        key=lambda pair: (pair[1] is not None, pair[1].position if pair[1] else -1),
        reverse=True,
    )


async def _state(api: Any, guild_id: int) -> tuple[dict, dict, dict]:
    return (
        await api.module_instance(guild_id, "tags"),
        await api.tags_draft_bindings(guild_id),
        await api.tags_diagnostics(guild_id),
    )


def _overview_payload(
    instance: dict,
    draft: dict,
    diagnostics: dict,
    *,
    highest_role: str,
    missing_roles: int,
) -> dict:
    lifecycle = instance["lifecycle"]
    published = int(draft["base_published_version"] or 0)
    status = {
        "active": "🟢 Ativo",
        "paused": "🟡 Pausado",
        "degraded": "🔴 Degradado",
        "inactive": "⚪ Inativo",
    }.get(lifecycle, "⚪ Indisponível")
    last_run = diagnostics.get("last_run") or {}
    run_text = (
        f"{last_run.get('status')} · {last_run.get('planned_items', 0)}/{last_run.get('total_items', 0)}"
        if last_run
        else "Nenhuma sincronização executada"
    )
    return payload(
        container(
            dashboard.module_navigation("tags"),
            separator(),
            text_display("# 🏷️ Sistema de Tags\n\nEscolhe uma Tag pela hierarquia atual dos cargos e mantém o apelido do membro reconciliado."),
            separator(),
            text_display(
                f"### Status\n**{status}** · versão publicada **{published or 'nenhuma'}**\n"
                f"Rascunho: **{len(draft['bindings'])} vínculo(s)** · revisão **{draft['revision']}**\n"
                f"Cargo configurado mais alto: **{highest_role}** · ausentes: **{missing_roles}**\n"
                f"Último run: **{run_text}**"
            ),
            action_row(
                button(custom_id=dashboard.central_custom_id("tags", "open_system"), label="Configurar vínculos", emoji="⚙️", style=2),
                button(custom_id=dashboard.central_custom_id("tags", "preview"), label="Pré-visualizar", emoji="👁️", style=2),
            ),
            accent_color=COLOR,
        )
    )


def _detail_payload(
    *,
    draft: dict,
    lifecycle: str,
    last_run: dict,
    lines: list[str],
    current_page: int,
    max_page: int,
) -> dict:
    status = {
        "active": "🟢 ativo",
        "paused": "🟡 pausado",
        "degraded": "🔴 com problema",
        "inactive": "⚪ inativo",
    }.get(lifecycle, "⚪ indisponível")
    processed = sum(
        int(last_run.get(key, 0) or 0)
        for key in ("succeeded_items", "skipped_items", "blocked_items", "failed_items")
    )
    run_text = (
        f"{last_run.get('status')} · {processed}/{int(last_run.get('total_items', 0) or 0)} processados"
        if last_run
        else "nenhuma aplicação executada"
    )
    components = [
        dashboard.module_navigation("tags"),
        separator(),
        text_display(
            "# 🏷️ Sistema de Tags\n\n"
            "As alterações ficam salvas aqui e só mudam os apelidos quando você confirma.\n\n"
            f"### Vínculos para confirmar · página {current_page + 1}/{max_page + 1}\n"
            + "\n".join(lines)
            + f"\n\nSistema **{status}** · publicação **{draft['base_published_version'] or 'nenhuma'}**"
            + f"\nÚltima aplicação: **{run_text}**"
        ),
        action_row(
            button(custom_id=dashboard.central_custom_id("tags", "add_binding"), label="Adicionar vínculo", emoji="➕", style=1),
            button(custom_id=dashboard.central_custom_id("tags", "manage_binding"), label="Editar vínculo", emoji="✏️", style=2, disabled=not bool(draft["bindings"])),
        ),
    ]
    if max_page > 0:
        components.append(
            action_row(
                button(custom_id=dashboard.central_custom_id("tags", "page_prev"), label="Anterior", style=2, disabled=current_page == 0),
                button(custom_id=dashboard.central_custom_id("tags", "page_next"), label="Próxima", style=2, disabled=current_page >= max_page),
            )
        )
    components.extend(
        [
            action_row(
                button(custom_id=dashboard.central_custom_id("tags", "confirm_publish"), label="Confirmar e aplicar", emoji="✅", style=3),
                button(custom_id=dashboard.central_custom_id("tags", "cleanup"), label="Limpar todas as Tags", emoji="🧹", style=4, disabled=not bool(draft["base_published_version"])),
            ),
            action_row(
                button(custom_id=dashboard.central_custom_id("tags", "preview"), label="Pré-visualizar", emoji="👁️", style=2),
                button(custom_id=dashboard.central_custom_id("tags", "advanced"), label="Opções avançadas", emoji="⚙️", style=2),
            ),
        ]
    )
    return payload(container(*components, accent_color=COLOR))


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    try:
        instance, draft, diagnostics = await _state(api, interaction.guild_id)
        sorted_items = _sort_bindings(interaction.guild, draft["bindings"])
        highest = next(
            (role.mention for item, role in sorted_items if role is not None and item["enabled"]),
            "nenhum",
        )
        missing = sum(1 for _, role in sorted_items if role is None)
        await _replace(
            interaction,
            _overview_payload(
                instance,
                draft,
                diagnostics,
                highest_role=highest,
                missing_roles=missing,
            ),
        )
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def _render_detail(
    interaction: discord.Interaction,
    api: Any,
    *,
    page: int | None = None,
    channel_id: int | None = None,
    message_id: int | None = None,
) -> None:
    instance, draft, diagnostics = await _state(api, interaction.guild_id)
    key = (interaction.guild_id, interaction.user.id)
    current = max(0, page if page is not None else _pages.get(key, 0))
    sorted_items = _sort_bindings(interaction.guild, draft["bindings"])
    max_page = max(0, (len(sorted_items) - 1) // 15)
    current = min(current, max_page)
    _pages[key] = current
    rows = sorted_items[current * 15 : current * 15 + 15]
    lines = []
    for item, role in rows:
        role_text = role.mention if role else f"⚠️ Cargo ausente ({item['discord_role_id']})"
        state = "ativo" if item["enabled"] else "inativo"
        lines.append(f"{role_text} → `{item['tag']}` · {state}")
    if not lines:
        lines.append("_Nenhum vínculo no rascunho._")
    await _replace(
        interaction,
        _detail_payload(
            draft=draft,
            lifecycle=instance["lifecycle"],
            last_run=diagnostics.get("last_run") or {},
            lines=lines,
            current_page=current,
            max_page=max_page,
        ),
        channel_id=channel_id,
        message_id=message_id,
    )


async def _render_advanced(interaction: discord.Interaction, api: Any) -> None:
    instance, draft, diagnostics_data = await _state(api, interaction.guild_id)
    lifecycle = instance["lifecycle"]
    last_run = diagnostics_data.get("last_run") or {}
    toggle_label = "Desativar sistema" if lifecycle == "active" else "Ativar sistema"
    await _replace(
        interaction,
        payload(
            container(
                dashboard.module_navigation("tags"),
                separator(),
                text_display(
                    "# ⚙️ Opções avançadas\n\n"
                    f"Sistema: **{lifecycle}**\n"
                    f"Última execução: **{last_run.get('status', 'nenhuma')}**\n\n"
                    "Use estas ações apenas para operação e diagnóstico."
                ),
                action_row(
                    button(custom_id=dashboard.central_custom_id("tags", "toggle_lifecycle"), label=toggle_label, style=2, disabled=not draft["base_published_version"]),
                    button(custom_id=dashboard.central_custom_id("tags", "sync"), label="Sincronizar novamente", emoji="🔄", style=1, disabled=lifecycle != "active"),
                    button(custom_id=dashboard.central_custom_id("tags", "cancel_run"), label="Cancelar execução", style=4, disabled=last_run.get("status") not in {"pending", "planning", "running"}),
                ),
                action_row(
                    button(custom_id=dashboard.central_custom_id("tags", "diagnostics"), label="Diagnóstico geral", emoji="🩺", style=2),
                    button(custom_id=dashboard.central_custom_id("tags", "diagnose_member"), label="Diagnosticar membro", style=2),
                    button(custom_id=dashboard.central_custom_id("tags", "open_system"), label="Voltar aos vínculos", emoji="↩️", style=2),
                ),
                accent_color=COLOR,
            )
        ),
    )


async def advanced(interaction: discord.Interaction, api: Any) -> None:
    await _render_advanced(interaction, api)


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    await _render_detail(interaction, api, page=0)


async def page_prev(interaction: discord.Interaction, api: Any) -> None:
    key = (interaction.guild_id, interaction.user.id)
    await _render_detail(interaction, api, page=_pages.get(key, 0) - 1)


async def page_next(interaction: discord.Interaction, api: Any) -> None:
    key = (interaction.guild_id, interaction.user.id)
    await _render_detail(interaction, api, page=_pages.get(key, 0) + 1)


async def back(interaction: discord.Interaction, api: Any) -> None:
    del api
    await _replace(interaction, dashboard.build_payload({}))


class BindingModal(discord.ui.Modal):
    def __init__(
        self,
        api: Any,
        role_id: int,
        *,
        enabled: bool = True,
        current_tag: str = "",
        channel_id: int,
        message_id: int,
    ) -> None:
        super().__init__(title="Configurar Tag", timeout=300)
        self.api = api
        self.role_id = role_id
        self.enabled = enabled
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        self.tag_input = discord.ui.TextInput(
            label="Tag (inclua os colchetes, se desejar)",
            placeholder="[MEM]",
            default=current_tag or None,
            min_length=1,
            max_length=24,
        )
        self.add_item(self.tag_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True)
            draft = await self.api.tags_draft_bindings(interaction.guild_id)
            await self.api.tags_upsert_binding(
                interaction.guild_id,
                {
                    "discord_role_id": str(self.role_id),
                    "guild_role_ids": [str(role.id) for role in interaction.guild.roles],
                    "tag": str(self.tag_input.value),
                    "enabled": self.enabled,
                    "expected_revision": draft["revision"],
                    "expected_published_version": draft["base_published_version"],
                },
                actor=actor_from(interaction),
            )
            await interaction.followup.send("Vínculo salvo. Use **Confirmar e aplicar** quando terminar.", ephemeral=True)
            await _render_detail(
                interaction,
                self.api,
                channel_id=self.central_channel_id,
                message_id=self.central_message_id,
            )
        except Exception as exc:
            await _reply(interaction, _error_text(exc))


class RolePickerView(discord.ui.View):
    def __init__(self, api: Any, *, channel_id: int, message_id: int) -> None:
        super().__init__(timeout=300)
        self.api = api
        self.channel_id = channel_id
        self.message_id = message_id
        select = discord.ui.RoleSelect(placeholder="Selecione o cargo que fornecerá a Tag")
        select.callback = self._selected  # type: ignore[method-assign]
        self.add_item(select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        values = getattr(self.children[0], "values", [])
        role = values[0] if values else None
        if role is None or role.is_default():
            await interaction.response.send_message("O cargo @everyone não pode receber Tag.", ephemeral=True)
            return
        await interaction.response.send_modal(
            BindingModal(
                self.api,
                role.id,
                channel_id=self.channel_id,
                message_id=self.message_id,
            )
        )


async def add_binding(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_message(
        "Selecione um cargo. A prioridade continuará sendo a hierarquia ao vivo do Discord.",
        view=RolePickerView(api, channel_id=interaction.channel_id, message_id=interaction.message.id),
        ephemeral=True,
    )


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, api: Any, binding: dict, *, channel_id: int, message_id: int) -> None:
        super().__init__(timeout=120)
        self.api = api
        self.binding = binding
        self.channel_id = channel_id
        self.message_id = message_id

    @discord.ui.button(label="Confirmar remoção", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.defer(ephemeral=True)
        try:
            draft = await self.api.tags_draft_bindings(interaction.guild_id)
            await self.api.tags_delete_binding(
                interaction.guild_id,
                self.binding["discord_role_id"],
                {
                    "expected_revision": draft["revision"],
                    "expected_published_version": draft["base_published_version"],
                },
                actor=actor_from(interaction),
            )
            await interaction.followup.send("Vínculo removido do rascunho.", ephemeral=True)
            await _render_detail(interaction, self.api, channel_id=self.channel_id, message_id=self.message_id)
        except Exception as exc:
            await _reply(interaction, _error_text(exc))


class BindingActionsView(discord.ui.View):
    def __init__(self, api: Any, binding: dict, *, channel_id: int, message_id: int) -> None:
        super().__init__(timeout=300)
        self.api = api
        self.binding = binding
        self.channel_id = channel_id
        self.message_id = message_id

    @discord.ui.button(label="Editar Tag", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(
            BindingModal(
                self.api,
                int(self.binding["discord_role_id"]),
                enabled=self.binding["enabled"],
                current_tag=self.binding["tag"],
                channel_id=self.channel_id,
                message_id=self.message_id,
            )
        )

    @discord.ui.button(label="Ativar/desativar", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.defer(ephemeral=True)
        try:
            draft = await self.api.tags_draft_bindings(interaction.guild_id)
            await self.api.tags_upsert_binding(
                interaction.guild_id,
                {
                    "discord_role_id": self.binding["discord_role_id"],
                    "guild_role_ids": [str(role.id) for role in interaction.guild.roles],
                    "tag": self.binding["tag"],
                    "enabled": not self.binding["enabled"],
                    "expected_revision": draft["revision"],
                    "expected_published_version": draft["base_published_version"],
                },
                actor=actor_from(interaction),
            )
            await interaction.followup.send("Estado atualizado no rascunho.", ephemeral=True)
            await _render_detail(interaction, self.api, channel_id=self.channel_id, message_id=self.message_id)
        except Exception as exc:
            await _reply(interaction, _error_text(exc))

    @discord.ui.button(label="Remover", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_message(
            "Confirme a remoção. Os apelidos só mudarão quando você usar **Confirmar e aplicar**.",
            view=ConfirmDeleteView(
                self.api,
                self.binding,
                channel_id=self.channel_id,
                message_id=self.message_id,
            ),
            ephemeral=True,
        )


class BindingPickerView(discord.ui.View):
    def __init__(self, api: Any, bindings: list[dict], guild: discord.Guild, *, channel_id: int, message_id: int) -> None:
        super().__init__(timeout=300)
        self.api = api
        self.bindings = {str(item["discord_role_id"]): item for item in bindings}
        options = []
        for item, role in _sort_bindings(guild, bindings)[:25]:
            options.append(
                discord.SelectOption(
                    label=(role.name if role else "Cargo ausente")[:100],
                    value=str(item["discord_role_id"]),
                    description=f"{item['tag']} · {'ativo' if item['enabled'] else 'inativo'}"[:100],
                )
            )
        select = discord.ui.Select(placeholder="Selecione o vínculo", options=options)
        select.callback = self._selected  # type: ignore[method-assign]
        self.add_item(select)
        self.channel_id = channel_id
        self.message_id = message_id

    async def _selected(self, interaction: discord.Interaction) -> None:
        values = getattr(self.children[0], "values", [])
        binding = self.bindings.get(values[0]) if values else None
        if binding is None:
            await interaction.response.send_message("Vínculo indisponível.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Gerenciar `{binding['tag']}`.",
            view=BindingActionsView(
                self.api, binding, channel_id=self.channel_id, message_id=self.message_id
            ),
            ephemeral=True,
        )


async def manage_binding(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.tags_draft_bindings(interaction.guild_id)
    await interaction.response.send_message(
        "Escolha o vínculo que deseja editar.",
        view=BindingPickerView(
            api, draft["bindings"], interaction.guild,
            channel_id=interaction.channel_id, message_id=interaction.message.id
        ),
        ephemeral=True,
    )


def member_snapshot(guild: discord.Guild, member: discord.Member | None, user_id: int) -> dict:
    bot_member = guild.me
    hierarchy = [str(role.id) for role in guild.roles]
    return {
        "guild_id": str(guild.id),
        "discord_user_id": str(user_id),
        "member_found": member is not None,
        "role_ids": [str(role.id) for role in member.roles] if member else [],
        "hierarchy_role_ids": hierarchy,
        "current_nickname": member.nick if member else None,
        "is_bot": member.bot if member else False,
        "is_owner": guild.owner_id == user_id,
        "manage_nicknames": bool(bot_member and bot_member.guild_permissions.manage_nicknames),
        "bot_top_role_id": str(bot_member.top_role.id) if bot_member else None,
        "target_top_role_id": str(member.top_role.id) if member else None,
    }


class PreviewUserView(discord.ui.View):
    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api
        select = discord.ui.UserSelect(placeholder="Selecione um membro registrado")
        select.callback = self._selected  # type: ignore[method-assign]
        self.add_item(select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        values = getattr(self.children[0], "values", [])
        user = values[0] if values else None
        if user is None:
            await interaction.response.send_message("Selecione um membro.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        member = interaction.guild.get_member(user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except discord.NotFound:
                member = None
        try:
            result = await self.api.tags_preview(
                interaction.guild_id,
                {"snapshot": member_snapshot(interaction.guild, member, user.id), "source": "draft", "base_only": False},
                actor=actor_from(interaction),
            )
            if result.get("blocker"):
                message = f"Prévia bloqueada: **{result['blocker']}**."
            else:
                message = f"Apelido esperado: `{result['expected_nickname']}`\nCargo vencedor: {('<@&' + result['winning_role_id'] + '>') if result.get('winning_role_id') else 'nenhum'}"
            await interaction.followup.send(message, ephemeral=True)
        except Exception as exc:
            await _reply(interaction, _error_text(exc))


async def preview(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_message(
        "A prévia usa o rascunho e o estado atual do Discord, sem alterar o membro.",
        view=PreviewUserView(api),
        ephemeral=True,
    )


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer()
    try:
        draft = await api.tags_draft_bindings(interaction.guild_id)
        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_nicknames:
            await interaction.followup.send("Publicação bloqueada: o Yuno não possui Gerenciar Apelidos.", ephemeral=True)
            return
        actor = actor_from(interaction)
        await api.publish_configuration(
            interaction.guild_id,
            "tags",
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": [],
            },
            actor=actor,
        )
        instance = await api.module_instance(interaction.guild_id, "tags")
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                "tags",
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
            )
        run = await api.tags_create_run(
            interaction.guild_id,
            {
                "mode": "effective",
                "reason": "confirm_apply",
                "supersede_active": True,
            },
            actor=actor,
        )
        await interaction.followup.send(
            f"Tudo confirmado. Os vínculos foram publicados e a atualização dos apelidos foi iniciada (`{run['id']}`).",
            ephemeral=True,
        )
        await _render_detail(interaction, api)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def toggle_lifecycle(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer()
    try:
        actor = actor_from(interaction)
        instance = await api.module_instance(interaction.guild_id, "tags")
        target = "inactive" if instance["lifecycle"] == "active" else "active"
        await api.update_lifecycle(
            interaction.guild_id, "tags", lifecycle=target,
            expected_lifecycle=instance["lifecycle"], actor=actor,
        )
        if target == "active":
            await api.tags_create_run(
                interaction.guild_id, {"mode": "effective", "reason": "activated"}, actor=actor
            )
        await interaction.followup.send(
            "Sistema ativado e reconciliação solicitada." if target == "active" else "Sistema desativado. Os apelidos existentes foram preservados.",
            ephemeral=True,
        )
        await _render_advanced(interaction, api)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def sync(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer()
    try:
        run = await api.tags_create_run(
            interaction.guild_id, {"mode": "effective", "reason": "manual"}, actor=actor_from(interaction)
        )
        await interaction.followup.send(f"Sincronização durável criada: `{run['id']}`.", ephemeral=True)
        await _render_advanced(interaction, api)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def cancel_run(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer()
    try:
        diagnostics = await api.tags_diagnostics(interaction.guild_id)
        run = diagnostics.get("last_run")
        if not run or run.get("status") not in {"pending", "planning", "running"}:
            await interaction.followup.send("Não há run ativo para cancelar.", ephemeral=True)
            return
        await api.tags_cancel_run(interaction.guild_id, run["id"], actor=actor_from(interaction))
        await interaction.followup.send("Cancelamento solicitado. Itens já aplicados não serão desfeitos.", ephemeral=True)
        await _render_advanced(interaction, api)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def cleanup(interaction: discord.Interaction, api: Any) -> None:
    await _replace(
        interaction,
        payload(
            container(
                dashboard.module_navigation("tags"),
                separator(),
                text_display(
                    "# 🧹 Limpar todas as Tags\n\n"
                    "Isso remove as Tags dos apelidos de todos os membros registrados. "
                    "Os vínculos continuarão salvos, mas o sistema ficará inativo ao terminar para não recolocá-las.\n\n"
                    "Para usar as Tags novamente, basta clicar em **Confirmar e aplicar**."
                ),
                action_row(
                    button(custom_id=dashboard.central_custom_id("tags", "confirm_cleanup"), label="Sim, limpar todas", emoji="🧹", style=4),
                    button(custom_id=dashboard.central_custom_id("tags", "open_system"), label="Cancelar", style=2),
                ),
                accent_color=0xD83C3E,
            )
        ),
    )


async def confirm_cleanup(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer()
    try:
        actor = actor_from(interaction)
        instance = await api.module_instance(interaction.guild_id, "tags")
        if not instance.get("published_config_version_id"):
            await interaction.followup.send("Não existe uma configuração publicada para limpar.", ephemeral=True)
            return
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                "tags",
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
            )
        run = await api.tags_create_run(
            interaction.guild_id,
            {"mode": "base_only", "reason": "cleanup", "supersede_active": True},
            actor=actor,
        )
        await interaction.followup.send(
            f"Limpeza iniciada (`{run['id']}`). O sistema será desativado automaticamente ao terminar.",
            ephemeral=True,
        )
        await _render_detail(interaction, api)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def diagnostics(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer()
    try:
        data = await api.tags_diagnostics(interaction.guild_id)
        counts = data.get("intent_counts") or {}
        last_run = data.get("last_run") or {}
        await interaction.followup.send(
            "**Diagnóstico do Sistema de Tags**\n"
            f"Lifecycle: `{data.get('lifecycle')}`\n"
            f"Vínculos publicados: **{data.get('binding_count', 0)}**\n"
            f"Intents: `{counts}`\n"
            f"Último run: `{last_run.get('status', 'nenhum')}`",
            ephemeral=True,
        )
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


class DiagnosticsUserView(discord.ui.View):
    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api
        select = discord.ui.UserSelect(placeholder="Selecione o membro para diagnosticar")
        select.callback = self._selected  # type: ignore[method-assign]
        self.add_item(select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        values = getattr(self.children[0], "values", [])
        user = values[0] if values else None
        if user is None:
            await interaction.response.send_message("Selecione um membro.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        member = interaction.guild.get_member(user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except discord.NotFound:
                member = None
        try:
            data = await self.api.tags_member_live_diagnostics(
                interaction.guild_id,
                user.id,
                member_snapshot(interaction.guild, member, user.id),
                actor=actor_from(interaction),
            )
            identity = data.get("identity") or {}
            resolution = data.get("resolution") or {}
            await interaction.followup.send(
                "**Diagnóstico do membro**\n"
                f"Identidade: `{identity.get('status', 'ausente')}`\n"
                f"Base: `{identity.get('base_nickname', 'indisponível')}`\n"
                f"Atual: `{(data.get('discord') or {}).get('current_nickname') or 'sem nickname'}`\n"
                f"Esperado: `{resolution.get('expected_nickname') or 'indisponível'}`\n"
                f"Cargo vencedor: {('<@&' + resolution['winning_role_id'] + '>') if resolution.get('winning_role_id') else 'nenhum'}\n"
                f"Bloqueio: `{resolution.get('blocker') or 'nenhum'}`",
                ephemeral=True,
            )
        except Exception as exc:
            await _reply(interaction, _error_text(exc))


async def diagnose_member(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_message(
        "O diagnóstico lê identidade, cargos, permissões e resolução ao vivo.",
        view=DiagnosticsUserView(api),
        ephemeral=True,
    )


def _nickname_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def run_job(bot: discord.Client, api: Any, item: dict) -> dict:
    guild_id = int(item["guild_id"])
    correlation_id = str(item.get("correlation_id") or item["id"])
    actor = system_actor(bot, guild_id, correlation_id)
    if item["key"] in {"tags.run.plan", "tags.run.finalize", "tags.retention"}:
        result = await api.tags_run_job(item, actor=actor)
        if item["key"] == "tags.retention":
            log.info("retention_completed guild_id=%s deleted_runs=%s", guild_id, result.get("deleted_runs"))
        elif result.get("status") in {"completed", "completed_with_errors", "cancelled", "failed"}:
            log.info("sync_run_completed guild_id=%s run_id=%s status=%s", guild_id, result.get("id"), result.get("status"))
        else:
            log.info("sync_run_started guild_id=%s run_id=%s status=%s", guild_id, result.get("id"), result.get("status"))
        return result

    data = item.get("payload") or {}
    user_id = int(data["discord_user_id"])
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise RetryableJobError("Guild indisponivel no cache do bot.", retry_at=datetime.now(timezone.utc) + timedelta(seconds=60))
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    except discord.NotFound:
        member = None
    prepared = await api.tags_prepare(
        guild_id,
        {
            "intent_id": data["intent_id"],
            "revision": data["revision"],
            "run_item_id": data.get("run_item_id"),
            "snapshot": member_snapshot(guild, member, user_id),
        },
        actor=actor,
    )
    if prepared.get("terminal"):
        event = "member_sync_blocked" if prepared.get("state") == "blocked" else "member_sync_skipped"
        log.info("%s guild_id=%s user_id=%s result=%s", event, guild_id, user_id, prepared.get("result_code"))
        return prepared
    if prepared.get("action") == "retry_later":
        retry_at = datetime.fromisoformat(str(prepared["retry_at"]))
        raise RetryableJobError(
            "Outro worker ainda processa este membro.", retry_at=retry_at
        )
    token = prepared["processing_token"]
    expected = prepared["expected_nickname"]
    common = {
        "intent_id": data["intent_id"],
        "revision": data["revision"],
        "processing_token": token,
        "run_item_id": data.get("run_item_id"),
    }
    if member is None:
        await api.tags_complete(
            guild_id,
            {**common, "result": "blocked", "result_code": "member_not_found", "applied_nickname_hash": None},
            actor=actor,
        )
        return {"result": "blocked", "code": "member_not_found"}
    try:
        await member.edit(nick=expected, reason="Yuno Sistema de Tags")
    except discord.NotFound:
        await api.tags_complete(
            guild_id,
            {**common, "result": "blocked", "result_code": "member_not_found", "applied_nickname_hash": None},
            actor=actor,
        )
        return {"result": "blocked", "code": "member_not_found"}
    except discord.Forbidden:
        await api.tags_fail(
            guild_id,
            {**common, "error_code": "discord_forbidden", "error_detail": "Discord recusou a edicao.", "retryable": False},
            actor=actor,
        )
        log.warning("member_sync_blocked guild_id=%s user_id=%s code=discord_forbidden", guild_id, user_id)
        return {"result": "failed", "code": "discord_forbidden"}
    except discord.HTTPException as exc:
        retry_after = getattr(exc, "retry_after", None)
        delay = float(retry_after) if retry_after is not None else 60.0
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=max(1.0, delay))
        try:
            await api.tags_fail(
                guild_id,
                {**common, "error_code": f"discord_http_{exc.status}", "error_detail": "Falha transitoria do Discord.", "retryable": True},
                actor=actor,
            )
        finally:
            log.warning("member_sync_retrying guild_id=%s user_id=%s status=%s", guild_id, user_id, exc.status)
        raise RetryableJobError("Falha transitoria ao editar nickname.", retry_at=retry_at) from exc
    await api.tags_complete(
        guild_id,
        {**common, "result": "applied", "result_code": "nickname_updated", "applied_nickname_hash": _nickname_hash(expected)},
        actor=actor,
    )
    log.info("member_sync_succeeded guild_id=%s user_id=%s", guild_id, user_id)
    return {"result": "applied", "code": "nickname_updated"}
