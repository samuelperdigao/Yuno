from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any

import discord
import httpx

from yuno_bot.platform.contracts import ActorContext, InteractionResult, RoutedContext
from yuno_bot.platform.panels import PanelPublisher
from yuno_bot.platform.router import custom_id


COLOR = 0xFFC72C


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    permissions = tuple(name for name, enabled in member.guild_permissions if enabled) if member else ()
    role_ids = tuple(role.id for role in member.roles) if member else ()
    return ActorContext(
        guild_id=interaction.guild_id or 0,
        user_id=interaction.user.id if interaction.user else None,
        role_ids=role_ids,
        discord_permissions=permissions,
        channel_id=interaction.channel_id,
        category_id=getattr(interaction.channel, "category_id", None),
        actor_type="user",
        is_guild_owner=bool(interaction.guild and interaction.guild.owner_id == interaction.user.id),
        correlation_id=str(interaction.id),
    )


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "Operacao recusada.")
            if isinstance(detail, dict):
                return str(detail.get("detail") or detail.get("message") or detail)
            return str(detail)
        except Exception:
            return f"API recusou a operacao ({exc.response.status_code})."
    return "Nao consegui concluir a operacao."


def _id_list(value: str) -> list[str]:
    return re.findall(r"\d{5,32}", value)


def _parse_items(value: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in re.split(r"[\n,;]+", value):
        raw = raw.strip()
        if not raw:
            continue
        match = re.fullmatch(r"(\d+)\s*[:=]\s*(\d+(?:[.,]\d{1,3})?)", raw)
        if match is None:
            raise ValueError("Use uma linha por item no formato ID=quantidade.")
        items.append({"product_id": int(match.group(1)), "quantity": match.group(2).replace(",", ".")})
    if not items:
        raise ValueError("Informe ao menos um item.")
    return items


def _active_cycle(cycles: list[dict]) -> dict | None:
    return next((item for item in cycles if item["status"] == "active"), None)


def _cycle_embed(cycle: dict | None, title: str = "Central de Farm") -> discord.Embed:
    embed = discord.Embed(title=title, color=COLOR)
    if cycle is None:
        embed.description = "Nenhum ciclo ativo no momento."
        return embed
    embed.description = f"**{cycle['title']}**\nEstado: `{cycle['status']}`"
    for goal in cycle.get("goals", [])[:20]:
        embed.add_field(
            name=goal["product_name"],
            value=f"Meta: {goal['quantity_required']} {goal['unit']}",
            inline=True,
        )
    if len(cycle.get("goals", [])) > 20:
        embed.set_footer(text=f"Mais {len(cycle['goals']) - 20} produto(s) no ciclo.")
    return embed


async def render_public(context: dict) -> dict:
    cycle = context.get("cycle")
    view = discord.ui.View(timeout=None)
    active = bool(cycle and cycle.get("status") == "active")
    view.add_item(discord.ui.Button(label="Abrir meu ticket", emoji="🎫", style=discord.ButtonStyle.success, custom_id=custom_id("farm", "public", "open_own_ticket"), disabled=not active))
    view.add_item(discord.ui.Button(label="Meu progresso", emoji="📊", style=discord.ButtonStyle.secondary, custom_id=custom_id("farm", "public", "view_own"), disabled=not active))
    view.add_item(discord.ui.Button(label="Abrir para membro", emoji="👤", style=discord.ButtonStyle.secondary, custom_id=custom_id("farm", "public", "open_for_member"), disabled=not active))
    return {"embed": _cycle_embed(cycle), "view": view}


async def render_ticket(context: dict) -> dict:
    ticket = context.get("ticket") or {}
    progress = context.get("progress") or {"percent": 0, "items": {}}
    embed = discord.Embed(
        title=f"Farm de {ticket.get('member_display_name', 'membro')}",
        description=f"Progresso geral: **{progress.get('percent', 0)}%**\nEstado: `{ticket.get('status', 'open')}`",
        color=COLOR,
    )
    goals = {str(item["id"]): item for item in (context.get("cycle") or {}).get("goals", [])}
    for goal_id, item in list((progress.get("items") or {}).items())[:20]:
        goal = goals.get(str(goal_id), {})
        embed.add_field(
            name=goal.get("product_name", f"Meta {goal_id}"),
            value=f"{item['approved']}/{item['required']} ({item['percent']}%)",
            inline=True,
        )
    view = discord.ui.View(timeout=None)
    open_for_submission = ticket.get("status") == "open"
    view.add_item(discord.ui.Button(label="Registrar entrega", emoji="📦", style=discord.ButtonStyle.success, custom_id=custom_id("farm", "ticket", "submit_own"), disabled=not open_for_submission))
    view.add_item(discord.ui.Button(label="Atualizar progresso", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id=custom_id("farm", "ticket", "progress")))
    return {"embed": embed, "view": view}


async def render_review(context: dict) -> dict:
    queue_size = int(context.get("queue_size") or 0)
    embed = discord.Embed(
        title="Fila de revisao do Farm",
        description=f"Entregas aguardando decisao: **{queue_size}**\nUse o botao para abrir a fila atual.",
        color=COLOR,
    )
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Revisar entregas", emoji="✅", style=discord.ButtonStyle.primary, custom_id=custom_id("farm", "review", "review_queue")))
    return {"embed": embed, "view": view}


async def _ticket_owner(_interaction: discord.Interaction, panel: dict, api: Any) -> str | None:
    ticket = await api.farm_ticket(int(panel["guild_id"]), int(panel["resource_id"]))
    return ticket["member_id"]


async def _ensure_ticket_panel(interaction: discord.Interaction, api: Any, actor: ActorContext, ticket: dict) -> discord.abc.GuildChannel:
    assert interaction.guild is not None
    config = (await api.effective_configuration(interaction.guild.id, "farm"))["data"]
    panel = await api.ensure_panel(
        interaction.guild.id,
        "farm",
        {"panel_key": "ticket", "resource_type": "farm_ticket", "resource_id": str(ticket["id"]), "definition_version": 1, "recovery_policy": "automatic", "actor": actor.as_payload()},
        actor_id=actor.user_id,
        correlation_id=actor.correlation_id,
    )
    channel = interaction.guild.get_channel(int(panel["channel_id"])) if panel.get("channel_id") else None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        category_ids = [int(value) for value in config.get("ticket_category_ids") or []]
        category = next((interaction.guild.get_channel(value) for value in category_ids if isinstance(interaction.guild.get_channel(value), discord.CategoryChannel)), None)
        if category is None:
            raise RuntimeError("Nenhuma categoria de tickets configurada.")
        member = interaction.guild.get_member(int(ticket["member_id"]))
        if member is None:
            member = await interaction.guild.fetch_member(int(ticket["member_id"]))
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
        }
        if interaction.guild.me:
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True)
        safe = re.sub(r"[^a-z0-9-]", "-", member.display_name.casefold())[:60].strip("-") or str(member.id)
        channel = await category.create_text_channel(f"farm-{safe}", overwrites=overwrites, reason="Ticket Farm V2")
    full_ticket = await api.farm_ticket(interaction.guild.id, ticket["id"])
    progress = await api.farm_progress(interaction.guild.id, ticket["id"])
    cycles = await api.farm_cycles(interaction.guild.id)
    cycle = next(item for item in cycles if item["id"] == ticket["cycle_id"])
    await PanelPublisher(interaction.client, api).reconcile(
        guild=interaction.guild,
        module_key="farm",
        panel_key="ticket",
        channel_id=channel.id,
        actor=actor,
        resource_type="farm_ticket",
        resource_id=str(ticket["id"]),
        render_context={"ticket": full_ticket, "progress": progress, "cycle": cycle},
    )
    return channel


async def open_own_ticket(context: RoutedContext) -> InteractionResult:
    cycle_id = int(context.panel["resource_id"])
    ticket = await context.api.farm_open_ticket(context.actor.guild_id, cycle_id, context.actor.user_id, context.interaction.user.display_name, actor=context.actor)
    channel = await _ensure_ticket_panel(context.interaction, context.api, context.actor, ticket)
    return InteractionResult(content=f"Seu ticket esta em {channel.mention}.")


async def view_own(context: RoutedContext) -> InteractionResult:
    tickets = await context.api.farm_cycle_tickets(context.actor.guild_id, cycle_id=int(context.panel["resource_id"]), member_id=context.actor.user_id)
    if not tickets:
        return InteractionResult(content="Voce ainda nao abriu um ticket neste ciclo.")
    ticket = tickets[0]
    progress = await context.api.farm_progress(context.actor.guild_id, ticket["id"])
    embed = discord.Embed(title="Seu progresso no Farm", description=f"**{progress['percent']}%** concluido", color=COLOR)
    for goal_id, item in list(progress.get("items", {}).items())[:20]:
        embed.add_field(name=f"Meta {goal_id}", value=f"{item['approved']}/{item['required']} ({item['percent']}%)", inline=True)
    return InteractionResult(embed=embed)


class OpenForMemberView(discord.ui.View):
    def __init__(self, context: RoutedContext) -> None:
        super().__init__(timeout=120)
        self.context = context

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Selecione o membro", min_values=1, max_values=1)
    async def member(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        selected = select.values[0]
        actor = actor_from(interaction)
        try:
            ticket = await self.context.api.farm_open_ticket(interaction.guild_id, int(self.context.panel["resource_id"]), selected.id, selected.display_name, actor=actor)
            channel = await _ensure_ticket_panel(interaction, self.context.api, actor, ticket)
            await interaction.followup.send(f"Ticket de {selected.mention} criado em {channel.mention}.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)


async def open_for_member(context: RoutedContext) -> InteractionResult:
    return InteractionResult(content="Escolha quem sera o beneficiario do ticket:", view=OpenForMemberView(context))


class SubmissionModal(discord.ui.Modal, title="Registrar entrega do Farm"):
    quantities = discord.ui.TextInput(label="Metas e quantidades", placeholder="12=100\n15=25.5", style=discord.TextStyle.paragraph, max_length=1500)
    proof = discord.ui.TextInput(label="Link do comprovante", placeholder="Link da mensagem ou do anexo", max_length=2000)
    note = discord.ui.TextInput(label="Observacao", required=False, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, context: RoutedContext) -> None:
        super().__init__(timeout=300)
        self.context = context

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            parsed = _parse_items(str(self.quantities))
            items = [{"goal_id": item["product_id"], "quantity": item["quantity"]} for item in parsed]
            link = str(self.proof).strip()
            match = re.search(r"/channels/\d+/(\d+)/(\d+)", link)
            channel_id, message_id = (match.group(1), match.group(2)) if match else (str(interaction.channel_id), str(interaction.id))
            actor = actor_from(interaction)
            await self.context.api.farm_submit(
                interaction.guild_id,
                int(self.context.panel["resource_id"]),
                {"submitted_by": str(interaction.user.id), "items": items, "proofs": [{"channel_id": channel_id, "message_id": message_id, "url": link}], "note": str(self.note) or None, "idempotency_key": f"discord:{interaction.id}"},
                actor=actor,
            )
            await interaction.followup.send("Entrega registrada e enviada para revisao.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc) if not isinstance(exc, ValueError) else str(exc), ephemeral=True)


async def submit_own(context: RoutedContext) -> InteractionResult:
    return InteractionResult(modal=SubmissionModal(context))


async def ticket_progress(context: RoutedContext) -> InteractionResult:
    progress = await context.api.farm_progress(context.actor.guild_id, int(context.panel["resource_id"]))
    return InteractionResult(content=f"Progresso atualizado: **{progress['percent']}%**.")


class ReviewModal(discord.ui.Modal, title="Decidir entrega"):
    decision = discord.ui.TextInput(label="Decisao", placeholder="approved, rejected ou correction_requested", max_length=24)
    reason = discord.ui.TextInput(label="Justificativa", required=False, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, api: Any, submission_id: int) -> None:
        super().__init__(timeout=300)
        self.api = api
        self.submission_id = submission_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = actor_from(interaction)
        try:
            await self.api.farm_review(interaction.guild_id, self.submission_id, {"reviewer_id": str(interaction.user.id), "decision": str(self.decision).strip(), "reason": str(self.reason) or None, "idempotency_key": f"discord:{interaction.id}"}, actor=actor)
            await interaction.followup.send("Decisao registrada.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)


class ReviewQueueView(discord.ui.View):
    def __init__(self, api: Any, queue: list[dict]) -> None:
        super().__init__(timeout=180)
        self.api, self.queue, self.page = api, queue, 0
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        start = self.page * 25
        options = [discord.SelectOption(label=f"#{item['id']} · {item.get('member_display_name', item['member_id'])}"[:100], description=f"Ticket {item['ticket_id']} · {item['status']}"[:100], value=str(item["id"])) for item in self.queue[start : start + 25]]
        select = discord.ui.Select(placeholder="Escolha uma entrega", options=options)
        select.callback = self.choose
        self.select = select
        self.add_item(select)
        previous = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        next_page = discord.ui.Button(label="Proxima", style=discord.ButtonStyle.secondary, disabled=start + 25 >= len(self.queue))
        previous.callback = self.previous
        next_page.callback = self.next
        self.add_item(previous)
        self.add_item(next_page)

    async def choose(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ReviewModal(self.api, int(self.select.values[0])))

    async def previous(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(content=f"Pagina {self.page + 1} da fila:", view=self)

    async def next(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(content=f"Pagina {self.page + 1} da fila:", view=self)


async def review_queue(context: RoutedContext) -> InteractionResult:
    queue = await context.api.farm_review_queue(context.actor.guild_id)
    if not queue:
        return InteractionResult(content="A fila de revisao esta vazia.")
    return InteractionResult(content=f"{len(queue)} entrega(s) aguardando. Pagina 1:", view=ReviewQueueView(context.api, queue))


class ConfigModal(discord.ui.Modal, title="Destinos do Farm"):
    timezone = discord.ui.TextInput(label="Timezone IANA", default="America/Sao_Paulo", max_length=64)
    categories = discord.ui.TextInput(label="IDs das categorias de tickets", placeholder="Separe por espaco ou virgula", max_length=500)
    public_channel = discord.ui.TextInput(label="ID do canal do painel publico", max_length=32)
    review_channel = discord.ui.TextInput(label="ID do canal de revisao", max_length=32)
    log_channel = discord.ui.TextInput(label="ID do canal de logs", required=False, max_length=32)

    def __init__(self, api: Any, guild_id: int, draft: dict) -> None:
        super().__init__(timeout=300)
        self.api, self.guild_id, self.draft = api, guild_id, draft
        data = draft.get("data") or {}
        self.timezone.default = data.get("timezone", "America/Sao_Paulo")
        self.categories.default = " ".join(data.get("ticket_category_ids") or [])
        self.public_channel.default = data.get("public_panel_channel_id")
        self.review_channel.default = data.get("review_panel_channel_id")
        self.log_channel.default = data.get("log_channel_id")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = actor_from(interaction)
        data = {**(self.draft.get("data") or {}), "timezone": str(self.timezone).strip(), "ticket_category_ids": _id_list(str(self.categories)), "public_panel_channel_id": str(self.public_channel).strip(), "review_panel_channel_id": str(self.review_channel).strip(), "log_channel_id": str(self.log_channel).strip() or None}
        try:
            await self.api.save_configuration_draft(self.guild_id, "farm", {"expected_revision": self.draft["revision"], "expected_published_version": self.draft["base_published_version"], "schema_version": self.draft["schema_version"], "data": data}, actor=actor)
            await interaction.followup.send("Rascunho do Farm salvo. Publique quando estiver pronto.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)


class ProductModal(discord.ui.Modal, title="Criar produto do Farm"):
    name = discord.ui.TextInput(label="Nome", max_length=80)
    unit = discord.ui.TextInput(label="Unidade", placeholder="un, kg, caixa...", max_length=30)
    precision = discord.ui.TextInput(label="Casas decimais", default="0", max_length=1)
    description = discord.ui.TextInput(label="Descricao", required=False, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.api.farm_create_product(interaction.guild_id, {"name": str(self.name), "unit": str(self.unit), "precision": int(str(self.precision)), "description": str(self.description) or None}, actor=actor_from(interaction))
            await interaction.followup.send("Produto criado.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)


class TemplateModal(discord.ui.Modal, title="Criar template do Farm"):
    name = discord.ui.TextInput(label="Nome", max_length=100)
    items = discord.ui.TextInput(label="Produtos e quantidades", placeholder="1=100\n2=25.5", style=discord.TextStyle.paragraph, max_length=3000)
    description = discord.ui.TextInput(label="Descricao", required=False, style=discord.TextStyle.paragraph, max_length=1000)
    source_template_id = discord.ui.TextInput(label="ID da versao anterior", required=False, placeholder="Preencha para criar uma nova versao", max_length=12)

    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            source = int(str(self.source_template_id)) if str(self.source_template_id).strip() else None
            await self.api.farm_create_template(interaction.guild_id, {"name": str(self.name), "description": str(self.description) or None, "items": _parse_items(str(self.items))}, actor=actor_from(interaction), source_template_id=source)
            await interaction.followup.send("Template criado como rascunho.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(str(exc) if isinstance(exc, ValueError) else error_text(exc), ephemeral=True)


class CycleModal(discord.ui.Modal, title="Criar ciclo do Farm"):
    template_id = discord.ui.TextInput(label="ID do template ativo", max_length=12)
    title_input = discord.ui.TextInput(label="Titulo", max_length=120)
    starts = discord.ui.TextInput(label="Inicio ISO-8601", placeholder="2026-08-12T12:00:00-03:00", max_length=40)
    ends = discord.ui.TextInput(label="Fim ISO-8601", placeholder="2026-08-19T12:00:00-03:00", max_length=40)
    options = discord.ui.TextInput(label="Modo | prazo de revisao", placeholder="opt_in | 2026-08-20T12:00:00-03:00", required=False, max_length=100)

    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            effective = await self.api.effective_configuration(interaction.guild_id, "farm")
            parts = [part.strip() for part in str(self.options).split("|", 1)] if str(self.options).strip() else ["opt_in"]
            payload = {"template_id": int(str(self.template_id)), "title": str(self.title_input), "timezone": effective["data"]["timezone"], "starts_at": datetime.fromisoformat(str(self.starts)).isoformat(), "ends_at": datetime.fromisoformat(str(self.ends)).isoformat(), "review_deadline_at": datetime.fromisoformat(parts[1]).isoformat() if len(parts) > 1 and parts[1] else None, "participation_mode": parts[0] or "opt_in", "proof_required": bool(effective["data"].get("proof_required", True))}
            await self.api.farm_create_cycle(interaction.guild_id, payload, actor=actor_from(interaction))
            await interaction.followup.send("Ciclo criado como rascunho.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)


class DomainActionModal(discord.ui.Modal, title="Acao administrativa do Farm"):
    action = discord.ui.TextInput(label="Acao", placeholder="activate/archive_template, archive_product, schedule/close/cancel_cycle, assign_member", max_length=32)
    resource_id = discord.ui.TextInput(label="ID do recurso", max_length=12)
    revision = discord.ui.TextInput(label="Revisao", required=False, max_length=12)
    extra = discord.ui.TextInput(label="Extra", placeholder="Motivo ou ID do membro | nome", required=False, max_length=1000)

    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = actor_from(interaction)
        action, resource_id = str(self.action).strip(), int(str(self.resource_id))
        revision = int(str(self.revision) or "1")
        try:
            if action == "activate_template":
                await self.api.farm_activate_template(interaction.guild_id, resource_id, revision, actor=actor)
            elif action == "archive_template":
                await self.api.farm_archive_template(interaction.guild_id, resource_id, revision, actor=actor)
            elif action == "archive_product":
                await self.api.farm_archive_product(interaction.guild_id, resource_id, revision, actor=actor)
            elif action == "schedule_cycle":
                await self.api.farm_schedule_cycle(interaction.guild_id, resource_id, revision, actor=actor)
            elif action in {"close_cycle", "cancel_cycle"}:
                await self.api.farm_transition_cycle(interaction.guild_id, resource_id, revision, "close" if action == "close_cycle" else "cancel", actor=actor, reason=str(self.extra) or None)
            elif action == "assign_member":
                parts = [part.strip() for part in str(self.extra).split("|", 1)]
                await self.api.farm_assign_participant(interaction.guild_id, resource_id, int(parts[0]), parts[1] if len(parts) > 1 else parts[0], actor=actor)
            else:
                raise ValueError("Acao desconhecida.")
            await interaction.followup.send("Acao administrativa concluida.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(str(exc) if isinstance(exc, ValueError) else error_text(exc), ephemeral=True)


class PublishModal(discord.ui.Modal, title="Publicar Farm e permissoes"):
    participant_roles = discord.ui.TextInput(label="Cargos participantes", placeholder="IDs ou 'everyone'", required=False, max_length=500)
    manager_roles = discord.ui.TextInput(label="Cargos gestores", required=False, max_length=500)
    reviewer_roles = discord.ui.TextInput(label="Cargos revisores", required=False, max_length=500)

    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = actor_from(interaction)
        try:
            draft = await self.api.configuration_draft(interaction.guild_id, "farm")
            grants: list[dict] = []
            participant_value = str(self.participant_roles).strip()
            participant_subjects = [("everyone", "")] if participant_value.casefold() == "everyone" else [("role", value) for value in _id_list(participant_value)]
            for subject_type, subject_id in participant_subjects:
                grants.append({"capability": "farm.open_own_ticket", "subject_type": subject_type, "subject_id": subject_id})
            manager_caps = ("farm.manage_catalog", "farm.manage_cycles", "farm.open_ticket_for_member", "farm.open_own_ticket", "farm.view_all", "farm.close_cycle", "farm.recover_panels")
            for role_id in _id_list(str(self.manager_roles)):
                grants.extend({"capability": capability, "subject_type": "role", "subject_id": role_id} for capability in manager_caps)
            for role_id in _id_list(str(self.reviewer_roles)):
                grants.extend({"capability": capability, "subject_type": "role", "subject_id": role_id} for capability in ("farm.review", "farm.view_all"))
            await self.api.publish_configuration(interaction.guild_id, "farm", {"expected_revision": draft["revision"], "expected_published_version": draft["base_published_version"], "grants": grants}, actor=actor)
            await interaction.followup.send("Configuracao e permissoes do Farm publicadas.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)


class CutoverModal(discord.ui.Modal, title="Cutover ou rollback do Farm"):
    run_id = discord.ui.TextInput(label="ID da execucao de migracao", max_length=36)
    action = discord.ui.TextInput(label="Acao", placeholder="cutover ou rollback", max_length=8)
    confirmation = discord.ui.TextInput(label="Confirmacao", placeholder="Digite CONFIRMAR", max_length=9)

    def __init__(self, api: Any) -> None:
        super().__init__(timeout=300)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if str(self.confirmation).strip() != "CONFIRMAR":
            await interaction.followup.send("Confirmacao invalida; nada foi alterado.", ephemeral=True)
            return
        actor = actor_from(interaction)
        try:
            if str(self.action).strip() == "cutover":
                result = await self.api.cutover_migration(interaction.guild_id, str(self.run_id).strip(), actor=actor)
            elif str(self.action).strip() == "rollback":
                result = await self.api.rollback_migration(interaction.guild_id, str(self.run_id).strip(), actor=actor)
            else:
                raise ValueError("Acao deve ser cutover ou rollback.")
            await interaction.followup.send(f"Runtime atualizado. Migracao em estado `{result['state']}`.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(str(exc) if isinstance(exc, ValueError) else error_text(exc), ephemeral=True)


class AdminFarmView(discord.ui.View):
    def __init__(self, api: Any, owner_id: int, state: dict) -> None:
        super().__init__(timeout=300)
        self.api, self.owner_id, self.state = api, owner_id, state

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Esta sessao pertence a outro administrador.", ephemeral=True)
        return False

    @discord.ui.button(label="Destinos", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        draft = await self.api.configuration_draft(interaction.guild_id, "farm")
        await interaction.response.send_modal(ConfigModal(self.api, interaction.guild_id, draft))

    @discord.ui.button(label="Novo produto", emoji="📦", style=discord.ButtonStyle.secondary, row=0)
    async def product(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ProductModal(self.api))

    @discord.ui.button(label="Novo template", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def template(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TemplateModal(self.api))

    @discord.ui.button(label="Novo ciclo", emoji="🗓️", style=discord.ButtonStyle.secondary, row=0)
    async def cycle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CycleModal(self.api))

    @discord.ui.button(label="Acao por ID", emoji="🛠️", style=discord.ButtonStyle.secondary, row=1)
    async def action(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DomainActionModal(self.api))

    @discord.ui.button(label="Publicar", emoji="🚀", style=discord.ButtonStyle.primary, row=1)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(PublishModal(self.api))

    @discord.ui.button(label="Ativar runtime", emoji="▶️", style=discord.ButtonStyle.success, row=1)
    async def activate(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            current = await self.api.module_instance(interaction.guild_id, "farm")
            target = "active" if current["lifecycle"] != "active" else "paused"
            await self.api.update_lifecycle(interaction.guild_id, "farm", lifecycle=target, expected_lifecycle=current["lifecycle"], actor=actor_from(interaction))
            await interaction.followup.send(f"Lifecycle alterado para `{target}`.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)

    @discord.ui.button(label="Publicar paineis", emoji="🧩", style=discord.ButtonStyle.success, row=1)
    async def panels(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            actor = actor_from(interaction)
            config = (await self.api.effective_configuration(interaction.guild_id, "farm"))["data"]
            cycles = await self.api.farm_cycles(interaction.guild_id)
            cycle = _active_cycle(cycles) or next((item for item in cycles if item["status"] == "scheduled"), None)
            if cycle is None:
                raise RuntimeError("Crie e agende um ciclo antes de publicar o painel publico.")
            publisher = PanelPublisher(interaction.client, self.api)
            await publisher.reconcile(guild=interaction.guild, module_key="farm", panel_key="public", channel_id=int(config["public_panel_channel_id"]), actor=actor, resource_type="farm_cycle", resource_id=str(cycle["id"]), render_context={"cycle": cycle})
            queue = await self.api.farm_review_queue(interaction.guild_id)
            await publisher.reconcile(guild=interaction.guild, module_key="farm", panel_key="review", channel_id=int(config["review_panel_channel_id"]), actor=actor, render_context={"queue_size": len(queue)})
            await interaction.followup.send("Paineis publico e de revisao reconciliados.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc) if not isinstance(exc, RuntimeError) else str(exc), ephemeral=True)

    @discord.ui.button(label="Atualizar visao", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await render_admin(interaction, self.api, edit=True)

    @discord.ui.button(label="Preparar cutover", emoji="🧪", style=discord.ButtonStyle.secondary, row=2)
    async def prepare_cutover(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = actor_from(interaction)
        try:
            inventory = await self.api.farm_inventory(interaction.guild_id, actor=actor)
            run = await self.api.start_migration(interaction.guild_id, "farm", "farm-v2", actor=actor)
            counts = {"legacy": inventory["legacy_counts"], "domain": inventory["domain_counts"], "active_legacy_tickets": inventory["active_legacy_tickets"]}
            checksum = hashlib.sha256(json.dumps(counts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            validating = await self.api.update_migration(interaction.guild_id, run["id"], {"state": "validating", "checkpoint": {"automatic_import": False, "incompatible_writes": False}, "counts": counts, "checksum": checksum, "warnings": inventory["warnings"], "errors": []}, actor=actor)
            if inventory["cutover_ready"]:
                final = await self.api.update_migration(interaction.guild_id, run["id"], {"state": "ready", "checkpoint": validating["checkpoint"], "counts": counts, "checksum": checksum, "warnings": inventory["warnings"], "errors": []}, actor=actor)
                await interaction.followup.send(f"Inventario validado. Run `{final['id']}` pronta; o cutover ainda exige confirmacao separada.", ephemeral=True)
            else:
                final = await self.api.update_migration(interaction.guild_id, run["id"], {"state": "failed", "checkpoint": validating["checkpoint"], "counts": counts, "checksum": checksum, "warnings": inventory["warnings"], "errors": ["Tickets legados ativos bloqueiam o cutover."]}, actor=actor)
                await interaction.followup.send(f"Run `{final['id']}` bloqueada: encerre os tickets legados ativos.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(error_text(exc), ephemeral=True)

    @discord.ui.button(label="Cutover / rollback", emoji="↩️", style=discord.ButtonStyle.danger, row=2)
    async def cutover(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CutoverModal(self.api))


async def render_admin(interaction: discord.Interaction, api: Any, *, edit: bool = False) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)
    guild_id = interaction.guild_id
    try:
        instance = await api.module_instance(guild_id, "farm")
        draft = await api.configuration_draft(guild_id, "farm")
        products = await api.farm_products(guild_id)
        templates = await api.farm_templates(guild_id)
        cycles = await api.farm_cycles(guild_id)
        diagnostics = await api.diagnostics(guild_id, "farm")
        inventory = await api.farm_inventory(guild_id, actor=actor_from(interaction))
    except Exception as exc:
        await interaction.followup.send(error_text(exc), ephemeral=True)
        return
    active = _active_cycle(cycles)
    embed = discord.Embed(title="🌾 Farm V2 · Central administrativa", description="Dominio novo, isolado do runtime legado.", color=COLOR)
    embed.add_field(name="Runtime", value=f"`{instance['runtime_mode']}` · lifecycle `{instance['lifecycle']}`", inline=False)
    embed.add_field(name="Configuracao", value=f"Publicada: **{draft['base_published_version'] or 'nenhuma'}** · rascunho r{draft['revision']}", inline=False)
    product_lines = [f"`#{item['id']}` {item['name']} · {item['unit']} · r{item['revision']} · {item['status']}" for item in products[:12]]
    template_lines = [f"`#{item['id']}` {item['name']} v{item['version']} · r{item['revision']} · {item['status']}" for item in templates[:12]]
    cycle_lines = [f"`#{item['id']}` {item['title']} · r{item['revision']} · {item['status']}" for item in cycles[:12]]
    if len(products) > 12:
        product_lines.append(f"… e mais {len(products) - 12}")
    if len(templates) > 12:
        template_lines.append(f"… e mais {len(templates) - 12}")
    if len(cycles) > 12:
        cycle_lines.append(f"… e mais {len(cycles) - 12}")
    embed.add_field(name=f"Produtos ({len(products)})", value="\n".join(product_lines) or "Nenhum produto.", inline=False)
    embed.add_field(name=f"Templates ({len(templates)})", value="\n".join(template_lines) or "Nenhum template.", inline=False)
    embed.add_field(name=f"Ciclos ({len(cycles)})", value="\n".join(cycle_lines) or "Nenhum ciclo.", inline=False)
    embed.add_field(name="Ciclo ativo", value=active["title"] if active else "Nenhum", inline=True)
    embed.add_field(name="Legado", value=f"{inventory['active_legacy_tickets']} ticket(s) ativo(s) · corte: {'pronto' if inventory['cutover_ready'] else 'bloqueado'}", inline=False)
    issues = [item for item in diagnostics if item["status"] in {"WARNING", "ERROR"}]
    embed.add_field(name="Diagnostico", value="\n".join(f"• {item['summary']}" for item in issues[:5]) or "Sem alertas acionaveis.", inline=False)
    view = AdminFarmView(api, interaction.user.id, {"instance": instance, "draft": draft})
    if edit:
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def run_job(bot: discord.Client, api: Any, item: dict) -> dict:
    if item["key"] != "farm.panel.reconcile":
        return await api.run_farm_job(item)
    payload = item.get("payload") or {}
    panel_key = payload.get("panel_key")
    if not panel_key:
        return {"changed": False, "reason": "reconcile sem painel"}
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponivel para reconciliar painel.")
    actor = ActorContext(guild_id=guild.id, user_id=bot.user.id, role_ids=(), discord_permissions=(), channel_id=None, category_id=None, actor_type="system", is_guild_owner=False, correlation_id=item["correlation_id"])
    config = (await api.effective_configuration(guild.id, "farm"))["data"]
    render_context: dict[str, Any]
    if panel_key == "public":
        channel_id = int(config["public_panel_channel_id"])
        cycles = await api.farm_cycles(guild.id)
        cycle = next((value for value in cycles if str(value["id"]) == str(payload.get("resource_id"))), None)
        render_context = {"cycle": cycle}
    elif panel_key == "review":
        channel_id = int(config["review_panel_channel_id"])
        render_context = {"queue_size": len(await api.farm_review_queue(guild.id))}
    elif panel_key == "ticket":
        resource_id = str(payload.get("resource_id"))
        panel = await api.ensure_panel(guild.id, "farm", {"panel_key": "ticket", "resource_type": "farm_ticket", "resource_id": resource_id, "definition_version": 1, "recovery_policy": "automatic", "actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)
        if not panel.get("channel_id"):
            return {"changed": False, "reason": "ticket ainda sem canal"}
        channel_id = int(panel["channel_id"])
        ticket = await api.farm_ticket(guild.id, int(resource_id))
        cycles = await api.farm_cycles(guild.id)
        cycle = next(value for value in cycles if value["id"] == ticket["cycle_id"])
        render_context = {"ticket": ticket, "cycle": cycle, "progress": await api.farm_progress(guild.id, ticket["id"])}
    else:
        return {"changed": False, "reason": "painel desconhecido"}
    await PanelPublisher(bot, api).reconcile(guild=guild, module_key="farm", panel_key=panel_key, channel_id=channel_id, actor=actor, resource_type=payload.get("resource_type", ""), resource_id=payload.get("resource_id", ""), render_context=render_context)
    return {"changed": True, "panel_key": panel_key}


async def deliver_audit(bot: discord.Client, item: dict) -> str | None:
    channel = bot.get_channel(int(item["destination_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(item["destination_id"]))
    payload = item.get("payload") or {}
    embed = discord.Embed(title="Auditoria do Farm", description=f"Evento: `{payload.get('event', 'farm')}`", color=COLOR)
    for key in ("submission_id", "ticket_id", "member_id", "decision", "reviewer_id", "reason", "progress_percent"):
        if payload.get(key) is not None:
            embed.add_field(name=key.replace("_", " ").title(), value=str(payload[key])[:1024], inline=True)
    message = await channel.send(embed=embed)
    return str(message.id)


async def deliver_review_pending(bot: discord.Client, item: dict) -> str | None:
    channel = bot.get_channel(int(item["destination_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(item["destination_id"]))
    payload = item.get("payload") or {}
    embed = discord.Embed(title="Nova entrega aguardando revisao", description=f"Submissao **#{payload.get('submission_id')}** · {payload.get('member_display_name')}", color=COLOR)
    embed.add_field(name="Ticket", value=str(payload.get("ticket_id")), inline=True)
    message = await channel.send(embed=embed)
    return str(message.id)
