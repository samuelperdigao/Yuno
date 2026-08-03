import discord

from yuno_bot.commands.shared import YUNO_BLUE, YUNO_GOLD, YUNO_GREEN, YUNO_ORANGE, YUNO_RED


def farm_panel_embed(guild_name: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="Central de Tickets | Farm Semanal",
        description="\n".join(
            [
                "Acompanhe sua **meta ativa da semana** em um canal privado, organizado e acessivel apenas por voce e pela administracao.",
                "",
                "**Como funciona**",
                "- Um ticket individual por membro a cada semana",
                "- Registre entregas parciais durante a semana",
                "- Envie o comprovante de cada lancamento",
                "- Acompanhe seu progresso automaticamente",
                "",
                "**Antes de abrir**",
                "Confira se a meta semanal esta ativa e deixe o print do comprovante preparado.",
            ]
        ),
        color=YUNO_GOLD,
    )
    embed.set_footer(text=f"Sistema de Farm{f' - {guild_name}' if guild_name else ''}")
    return embed


def farm_goal_embed(week_id: str, items: list[dict], guild_name: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="Meta semanal de farm",
        description=f"Semana `{week_id}`{f' - {guild_name}' if guild_name else ''}",
        color=YUNO_BLUE,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Itens", value=format_goal_items(items), inline=False)
    embed.set_footer(text="Yuno - metas de farm")
    return embed


def farm_ranking_embed(data: dict, guild_name: str | None = None) -> discord.Embed:
    ranking = data.get("ranking") or []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines: list[str] = []
    for item in ranking:
        position = int(item.get("position") or len(lines) + 1)
        marker = medals.get(position, f"`#{position:02d}`")
        item_summary = " • ".join(
            f"{name}: **{int(quantity):,}**".replace(",", ".")
            for name, quantity in (item.get("items") or {}).items()
        )
        total = f"{int(item.get('delivered_total') or 0):,}".replace(",", ".")
        lines.append(
            f"{marker} <@{item['user_id']}> — **{total}** entregues "
            f"• {int(item.get('completion_percent') or 0)}% da meta\n"
            f"> {item_summary or 'Sem itens contabilizados'}"
        )

    embed = discord.Embed(
        title="🏆 Ranking Semanal de Farm",
        description="\n\n".join(lines) if lines else "Ainda não há entregas contabilizadas nesta semana.",
        color=YUNO_GOLD,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Semana", value=f"`{data.get('week_id')}`", inline=True)
    embed.add_field(name="Participantes", value=f"`{int(data.get('participants') or 0)}`", inline=True)
    embed.set_footer(text=f"Yuno • Farm{f' • {guild_name}' if guild_name else ''}")
    return embed


def farm_ticket_embed(ticket: dict, member: discord.Member | None = None) -> discord.Embed:
    status = ticket.get("status") or "aberto"
    color = YUNO_GREEN if status == "aprovado_total" else YUNO_ORANGE if status in {"revisao", "aprovado_parcial"} else YUNO_RED if status == "sem_entrega" else YUNO_BLUE
    progress = ticket.get("progress") or {}
    percent = int(progress.get("percent") or 0)
    embed = discord.Embed(
        title="Ticket Semanal de Farm",
        description=f"Semana `{ticket.get('week_id')}`\nStatus: `{status}`\nProgresso geral: `{percent}%`",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    owner = member.mention if member else f"<@{ticket.get('user_id')}>"
    embed.add_field(name="Membro", value=f"{owner}\n`{ticket.get('user_id')}`", inline=True)
    if ticket.get("folder_slot") is not None:
        embed.add_field(name="Slot da Pasta", value=f"`{int(ticket['folder_slot']):02d}`", inline=True)
        embed.add_field(name="Apelido", value=ticket.get("folder_nickname") or ticket.get("member_name") or "-", inline=True)
        if ticket.get("game_id"):
            embed.add_field(name="ID do Jogo", value=f"`{ticket['game_id']}`", inline=True)
        if ticket.get("folder_channel_id"):
            embed.add_field(name="Pasta Individual", value=f"<#{ticket['folder_channel_id']}>", inline=False)
    if ticket.get("assigned_to"):
        embed.add_field(name="Responsavel", value=f"<@{ticket['assigned_to']}>", inline=True)
    embed.add_field(name="Meta e progresso", value=format_progress(ticket), inline=False)
    entries = ticket.get("entries") or []
    embed.add_field(name="Lancamentos", value=str(len(entries)), inline=True)
    embed.set_footer(text=f"Yuno - farm ticket #{ticket.get('id')}")
    return embed


def farm_log_embed(action: dict) -> discord.Embed:
    action_name = (action.get("action") or "acao").replace("_", " ").title()
    embed = discord.Embed(title=f"Farm: {action_name}", color=YUNO_GOLD, timestamp=discord.utils.utcnow())
    if action.get("ticket_id"):
        embed.add_field(name="Ticket", value=f"#{action['ticket_id']}", inline=True)
    if action.get("actor_id"):
        embed.add_field(name="Ator", value=f"<@{action['actor_id']}>\n`{action['actor_id']}`", inline=True)
    payload = action.get("payload") or {}
    summary = "\n".join(f"**{key}:** `{value}`" for key, value in payload.items() if value is not None)
    if summary:
        embed.add_field(name="Detalhes", value=summary[:1024], inline=False)
    if payload.get("proof_url"):
        embed.set_image(url=payload["proof_url"])
    embed.set_footer(text="Yuno - log de farm")
    return embed


def format_goal_items(items: list[dict]) -> str:
    lines = []
    for item in items:
        name = item.get("name") or item.get("produto") or "Item"
        quantity = item.get("quantity") or item.get("quantidade") or 0
        lines.append(f"- **{name}**: `{quantity}`")
    return "\n".join(lines)[:1024] or "Nenhum item configurado."


def format_progress(ticket: dict) -> str:
    progress_items = ((ticket.get("progress") or {}).get("items") or {})
    if not progress_items:
        return format_goal_items(ticket.get("goal_items") or [])
    lines = []
    for name, data in progress_items.items():
        delivered = data.get("delivered") or 0
        required = data.get("required") or 0
        percent = data.get("percent") or 0
        lines.append(f"- **{name}**: `{delivered}/{required}` (`{percent}%`)")
    return "\n".join(lines)[:1024]


def recent_proofs_text(ticket: dict, limit: int = 5) -> str:
    entries = list(ticket.get("entries") or [])[-limit:]
    if not entries:
        return "Nenhum comprovante registrado ainda."
    lines = []
    for entry in entries:
        lines.append(f"#{entry['id']} - {entry.get('proof_url')}")
    return "\n".join(lines)[:1900]
