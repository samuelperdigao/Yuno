from datetime import datetime, timedelta, timezone

import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.ausencia.embeds import ausencia_channel_id, normalize_motivo, parse_dias
from yuno_bot.commands.shared import resolve_text_channel


class AusenciaRegistroModal(discord.ui.Modal, title="📋 Registrar Ausência"):
    dias = discord.ui.TextInput(
        label="Quantos dias ficará fora?",
        placeholder="Ex: 5 (máximo 7 dias)",
        required=True,
        max_length=2,
    )
    motivo = discord.ui.TextInput(
        label="Motivo da ausência",
        placeholder="Ex: Viagem, trabalho...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
    )

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ O módulo de Ausências não está configurado. Um administrador deve usar /setup_ausencia.", ephemeral=True)
            return

        try:
            dias = parse_dias(self.dias.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        inicio = datetime.now(timezone.utc)
        fim = inicio + timedelta(days=dias)
        motivo = normalize_motivo(self.motivo.value)

        try:
            config = await self.api.get_guild_config(interaction.guild.id)
            channel = await resolve_text_channel(interaction.guild, ausencia_channel_id(config))
        except httpx.HTTPError:
            channel = None

        if not channel:
            await interaction.response.send_message(
                "❌ O módulo de Ausências não está configurado. Um administrador deve usar /setup_ausencia.",
                ephemeral=True,
            )
            return

        try:
            ausencia = await self.api.upsert_ausencia(
                guild_id=interaction.guild.id,
                user_id=interaction.user.id,
                nome=interaction.user.display_name,
                dias=dias,
                motivo=motivo,
                inicio=inicio.isoformat(),
                fim=fim.isoformat(),
            )
        except httpx.HTTPError:
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            return

        from yuno_bot.commands.ausencia.cog import publish_ausencia_registration

        try:
            await publish_ausencia_registration(self.api, interaction, ausencia, channel=channel)
        except Exception:
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Ausência registrada! Confira em {channel.mention}.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
            return
        await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
