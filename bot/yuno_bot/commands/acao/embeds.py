import discord

from yuno_bot.commands.acao.helpers import format_money_centavos

COR_ACAO = discord.Color.gold()


def tipo_display(tipo: str | None) -> str:
    if tipo == "fuga":
        return "🏃 Fuga"
    if tipo == "tiro":
        return "🔫 No Tiro"
    return "Não informado"


def status_display(status: str, resultado: str | None) -> str:
    if status == "done":
        return "🏆 Ganha" if resultado == "ganha" else "❌ Perdida"
    return "🟢 Aberta"


def participante_value(participantes: list[dict]) -> str:
    if not participantes:
        return "Nenhum inscrito ainda"
    linhas = [f"• <@{p['user_id']}>" for p in participantes[:35]]
    if len(participantes) > 35:
        linhas.append(f"• ... +{len(participantes) - 35} participante(s)")
    return "\n".join(linhas)


def painel_fixo_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚡ Painel de Ação",
        description="Inicie uma ação clicando no botão abaixo.\n\nVocê irá definir o **horário**, a **data** e o **tipo** (fuga ou tiro) antes de escolher a missão.",
        color=COR_ACAO,
    )
    embed.set_footer(text="Sistema de Ação")
    return embed


def selecionar_acao_embed(*, data: str, horario: str, tipo: str) -> discord.Embed:
    embed = discord.Embed(
        title="⚡ Selecione a Ação",
        description="Escolha a missão no menu abaixo para abrir o painel de participantes.",
        color=COR_ACAO,
    )
    embed.add_field(name="📅 Data", value=data, inline=True)
    embed.add_field(name="🕐 Horário", value=horario, inline=True)
    embed.add_field(name="⚔️ Tipo", value=tipo_display(tipo), inline=True)
    embed.set_footer(text="Sistema de Ação")
    return embed


def tipo_sem_catalogo_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ Nenhuma missão cadastrada",
        description="Peça a um admin para cadastrar tipos de ação com `/acao tipo_criar`.",
        color=discord.Color.orange(),
    )
    return embed


def regras_embed(
    tipo_dict: dict,
    record: dict,
    participantes: list[dict],
) -> discord.Embed:
    payload = record["payload"]
    max_p = tipo_dict.get("max_participantes")
    color = discord.Color.green() if payload.get("resultado") == "ganha" else discord.Color.red() if payload.get("resultado") == "perdida" else COR_ACAO
    vagas = "Ver regras" if max_p is None else f"{len(participantes)}/{max_p}"

    embed = discord.Embed(
        title=f"{tipo_dict['emoji']} {tipo_dict['nome']}",
        description=f"**Status:** {status_display(record['status'], payload.get('resultado'))}",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="📅 Data", value=payload.get("data") or "-", inline=True)
    embed.add_field(name="🕐 Horário", value=payload.get("horario") or "-", inline=True)
    embed.add_field(name="⚔️ Tipo", value=tipo_display(payload.get("tipo")), inline=True)
    embed.add_field(name="👤 Criador", value=f"<@{record['requester_id']}>", inline=True)
    embed.add_field(name="🎟️ Vagas", value=vagas, inline=True)
    embed.add_field(name="​", value="​", inline=True)
    if tipo_dict.get("regras"):
        embed.add_field(name="📋 Regras", value=tipo_dict["regras"][:1024], inline=False)
    embed.add_field(name=f"✅ Participantes ({len(participantes)})", value=participante_value(participantes), inline=False)
    if record["status"] == "done" and payload.get("finalizado_por"):
        embed.add_field(name="🔒 Finalizada por", value=f"<@{payload['finalizado_por']}>", inline=True)
    if payload.get("observacao"):
        embed.add_field(name="📝 Observação", value=payload["observacao"][:1000], inline=False)
    embed.set_footer(text=f"Sistema de Ação · Ação #{record['id']}")
    return embed


def resultado_embed(tipo_dict: dict, record: dict, participantes: list[dict]) -> discord.Embed:
    payload = record["payload"]
    embed = discord.Embed(
        title=f"{status_display(record['status'], payload.get('resultado'))} — {tipo_dict['nome']}",
        color=discord.Color.green() if payload.get("resultado") == "ganha" else discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Data/Hora", value=f"{payload.get('data')} {payload.get('horario')}", inline=True)
    embed.add_field(name="Tipo", value=tipo_display(payload.get("tipo")), inline=True)
    embed.add_field(name="Finalizada por", value=f"<@{payload.get('finalizado_por')}>", inline=True)
    embed.add_field(name=f"Participantes ({len(participantes)})", value=participante_value(participantes), inline=False)
    if payload.get("observacao"):
        embed.add_field(name="Observação", value=payload["observacao"][:1000], inline=False)
    return embed


def pagamento_embed(tipo_dict: dict, record: dict, participantes: list[dict]) -> discord.Embed:
    payload = record["payload"]
    embed = discord.Embed(title=f"💰 Pagamento de Ação — {tipo_dict['nome']}", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Data/Hora", value=f"{payload.get('data')} {payload.get('horario')}", inline=True)
    embed.add_field(name="Participantes", value=str(len(participantes)), inline=True)
    embed.add_field(name="Valor total", value=format_money_centavos(payload.get("valor_total_centavos")), inline=True)
    embed.add_field(name="Facção", value=format_money_centavos(payload.get("valor_faccao_centavos")), inline=True)
    embed.add_field(name="Total participantes", value=format_money_centavos(payload.get("valor_participantes_centavos")), inline=True)
    embed.add_field(name="Por participante", value=format_money_centavos(payload.get("valor_por_participante_centavos")), inline=True)
    embed.add_field(name="Quem recebe", value=participante_value(participantes), inline=False)
    embed.set_footer(text="Regra: 50% participantes e 50% facção; sobra de arredondamento fica com a facção.")
    return embed


def catalogo_listagem_embed(tipos: list[dict]) -> discord.Embed:
    embed = discord.Embed(title="📋 Tipos de Ação Cadastrados", color=COR_ACAO)
    if not tipos:
        embed.description = "Nenhum tipo cadastrado ainda. Use `/acao tipo_criar`."
        return embed
    for tipo in tipos:
        max_p = tipo.get("max_participantes")
        vagas = f"máximo {max_p}" if max_p else "sem limite"
        embed.add_field(name=f"{tipo['emoji']} {tipo['nome']} (`{tipo['key']}`)", value=f"{vagas}\n{(tipo.get('regras') or '-')[:200]}", inline=False)
    return embed
