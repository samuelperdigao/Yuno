import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.acao.helpers import (
    calcular_pagamento,
    normalize_date_br,
    normalize_resultado,
    normalizar_horario,
    parse_money_centavos,
    upsert_tipo,
)
from yuno_bot.commands.shared import get_guild_config


class IniciarAcaoModal(discord.ui.Modal, title="⚡ Configurar Ação"):
    data = discord.ui.TextInput(label="Data da ação", placeholder="Ex: 08/06/2026", max_length=10)
    horario = discord.ui.TextInput(label="Horário da ação", placeholder="Ex: 21:00", max_length=5)

    def __init__(self, api: YunoAPI, tipo: str):
        super().__init__()
        self.api = api
        self.tipo = tipo

    async def on_submit(self, interaction: discord.Interaction) -> None:
        from yuno_bot.commands.acao.embeds import selecionar_acao_embed, tipo_sem_catalogo_embed
        from yuno_bot.commands.acao.views import AcaoSelectView

        try:
            data_val = normalize_date_br(self.data.value)
            horario_val = normalizar_horario(self.horario.value)
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use dentro de um canal de texto.", ephemeral=True)
            return

        config = await get_guild_config(self.api, interaction.guild_id)
        tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
        if not tipos:
            await interaction.response.send_message(embed=tipo_sem_catalogo_embed(), ephemeral=True)
            return

        embed = selecionar_acao_embed(data=data_val, horario=horario_val, tipo=self.tipo)
        view = AcaoSelectView(self.api, horario=horario_val, tipo=self.tipo, data=data_val, tipos=tipos)
        await interaction.response.send_message(embed=embed, view=view)


class FinalizarAcaoModal(discord.ui.Modal, title="🔒 Finalizar Ação"):
    resultado = discord.ui.TextInput(label="Resultado", placeholder="vitória/ganha ou derrota/perdida", max_length=20)
    valor_total = discord.ui.TextInput(label="Valor total (obrigatório se vitória)", placeholder="Ex: R$ 50.000,00", max_length=30, required=False)
    observacao = discord.ui.TextInput(label="Observação", style=discord.TextStyle.paragraph, max_length=1000, required=False)

    def __init__(self, api: YunoAPI, acao_id: int, participantes_count: int):
        super().__init__()
        self.api = api
        self.acao_id = acao_id
        self.participantes_count = participantes_count

    async def on_submit(self, interaction: discord.Interaction) -> None:
        from yuno_bot.commands.acao.views import finalize_acao

        try:
            resultado_val = normalize_resultado(self.resultado.value)
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return

        pagamento = {
            "valor_total_centavos": None,
            "valor_faccao_centavos": None,
            "valor_participantes_centavos": None,
            "valor_por_participante_centavos": None,
        }
        if resultado_val == "ganha":
            if self.participantes_count <= 0:
                await interaction.response.send_message(
                    "Vitória precisa ter pelo menos um participante para calcular pagamento.", ephemeral=True
                )
                return
            try:
                pagamento = calcular_pagamento(parse_money_centavos(self.valor_total.value), self.participantes_count)
            except ValueError as exc:
                await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)
        try:
            await finalize_acao(
                self.api,
                interaction,
                acao_id=self.acao_id,
                resultado=resultado_val,
                observacao=self.observacao.value.strip() or None,
                pagamento=pagamento,
            )
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui finalizar a ação agora.", ephemeral=True)


class TipoRegrasModal(discord.ui.Modal, title="Regras da Missão"):
    regras = discord.ui.TextInput(
        label="Regras (armamento, negociação, reféns...)",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False,
    )

    def __init__(self, api: YunoAPI, *, chave: str, nome: str, emoji: str, max_participantes: int | None):
        super().__init__()
        self.api = api
        self.chave = chave
        self.nome = nome
        self.emoji = emoji
        self.max_participantes = max_participantes

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            config = await self.api.get_guild_config(interaction.guild_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send("Este servidor ainda não possui licença ativa.", ephemeral=True)
                return
            await interaction.followup.send("Não consegui carregar a configuração do servidor.", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui falar com a API do Yuno.", ephemeral=True)
            return

        settings = dict(config.get("settings") or {})
        acao_settings = dict(settings.get("acao") or {})
        tipos = upsert_tipo(
            list(acao_settings.get("tipos") or []),
            key=self.chave,
            nome=self.nome,
            emoji=self.emoji,
            max_participantes=self.max_participantes,
            regras=self.regras.value.strip(),
        )
        acao_settings["tipos"] = tipos
        settings["acao"] = acao_settings
        updated_config = {
            "guild_name": config.get("guild_name"),
            "admin_role_ids": config.get("admin_role_ids") or [],
            "log_channel_id": config.get("log_channel_id"),
            "modules": config.get("modules") or {},
            "command_permissions": config.get("command_permissions") or {},
            "messages": config.get("messages") or {},
            "settings": settings,
        }
        try:
            await self.api.save_guild_config(interaction.guild_id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui salvar o catálogo de ações.", ephemeral=True)
            return

        await interaction.followup.send(f"Tipo de ação **{self.nome}** cadastrado.", ephemeral=True)
