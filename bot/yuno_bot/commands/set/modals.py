import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.set.actions import approve_set_record, reject_set_record
from yuno_bot.commands.set.embeds import approved_public_embed, build_set_payload, created_log_embed, rejected_public_embed, request_embed
from yuno_bot.commands.set.views import SetApprovalView
from yuno_bot.commands.shared import create_record, parse_positive_int, send_module_log, send_to_setup_channel


class SetSolicitarModal(discord.ui.Modal, title="Solicitacao de Set"):
    id_fivem = discord.ui.TextInput(label="ID no Jogo", placeholder="Ex: 12345", max_length=20)
    nome = discord.ui.TextInput(label="Nome do Membro", placeholder="Ex: Joao Silva", max_length=32)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            parse_positive_int(self.id_fivem.value, "ID FiveM")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return

        payload = build_set_payload(self.nome.value, self.id_fivem.value)
        if not payload["nome"]:
            await interaction.response.send_message("Erro: Nome do Membro precisa ser informado.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            record = await create_record(self.api, interaction, module="set", title=f"Set de {payload['nome']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar sua solicitacao agora.", ephemeral=True)
            return

        view = SetApprovalView(self.api, int(record["id"]))
        approval_message = await send_to_setup_channel(
            self.api,
            interaction,
            "set_aprovacao",
            embed=request_embed(interaction, record, payload),
            view=view,
        )
        await send_module_log(self.api, interaction, "set", created_log_embed(interaction, record, payload))
        if approval_message:
            await interaction.followup.send(f"Solicitacao enviada para aprovacao. Protocolo #{record['id']}.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Solicitacao registrada como protocolo #{record['id']}, mas nao encontrei o canal de aprovacao.",
            ephemeral=True,
        )


class SetAprovarModal(discord.ui.Modal, title="Aprovar Set"):
    protocolo = discord.ui.TextInput(label="Protocolo", placeholder="Ex: 12", max_length=12)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            protocolo = parse_positive_int(self.protocolo.value, "Protocolo")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        record, message = await approve_set_record(self.api, interaction, protocolo)
        if not record:
            await interaction.followup.send(message, ephemeral=True)
            return
        await _send_public_embed(interaction, approved_public_embed(interaction, record, message))
        await interaction.followup.send(f"Set #{protocolo} aprovado. {message}", ephemeral=True)


class SetReprovarModal(discord.ui.Modal, title="Reprovar Set"):
    protocolo = discord.ui.TextInput(label="Protocolo", placeholder="Ex: 12", max_length=12)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, api: YunoAPI, protocolo: int | None = None, source_message: discord.Message | None = None):
        super().__init__()
        self.api = api
        self.source_message = source_message
        if protocolo is not None:
            self.protocolo.default = str(protocolo)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            protocolo = parse_positive_int(self.protocolo.value, "Protocolo")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return
        motivo = self.motivo.value.strip()
        if not motivo:
            await interaction.response.send_message("Erro: Motivo precisa ser informado.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        record, message = await reject_set_record(self.api, interaction, protocolo, motivo)
        if not record:
            await interaction.followup.send(message, ephemeral=True)
            return
        if self.source_message:
            try:
                await self.source_message.edit(view=None)
            except discord.HTTPException:
                pass
        await _send_public_embed(interaction, rejected_public_embed(interaction, record, motivo))
        await interaction.followup.send(f"Set #{protocolo} reprovado.", ephemeral=True)


async def _send_public_embed(interaction: discord.Interaction, embed: discord.Embed) -> None:
    if not interaction.channel:
        return
    try:
        await interaction.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
    except discord.HTTPException:
        pass
