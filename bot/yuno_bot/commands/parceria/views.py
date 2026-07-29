import asyncio
import io

import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.parceria.embeds import (
    is_valid_image_attachment,
    parceria_active_embed,
    uniform_filename,
)
from yuno_bot.commands.parceria.permissions import can_manage_parcerias
from yuno_bot.commands.parceria.repository import ParceriaDuplicadaError, ParceriasRepository
from yuno_bot.commands.shared import resolve_text_channel


class ParceriaPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI, repository: ParceriasRepository):
        super().__init__(timeout=None)
        self.api = api
        self.repository = repository

    @discord.ui.button(label="Registrar Parceria", emoji="🤝", style=discord.ButtonStyle.primary, custom_id="yuno:parcerias:registrar")
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await can_manage_parcerias(interaction, self.api, command="registrar"):
            await interaction.response.send_message("Sem permissão para registrar parcerias.", ephemeral=True)
            return
        await interaction.response.send_modal(ParceriaRegisterModal(self.repository))

    @discord.ui.button(label="Editar Parceria", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="yuno:parcerias:editar")
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await can_manage_parcerias(interaction, self.api, command="editar"):
            await interaction.response.send_message("Sem permissão para gerenciar parcerias.", ephemeral=True)
            return
        await _send_active_select(interaction, self.repository, mode="edit")

    @discord.ui.button(label="Remover Parceria", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="yuno:parcerias:remover")
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await can_manage_parcerias(interaction, self.api, command="remover"):
            await interaction.response.send_message("Sem permissão para gerenciar parcerias.", ephemeral=True)
            return
        await _send_active_select(interaction, self.repository, mode="remove")


class ParceriaRegisterModal(discord.ui.Modal, title="Registrar Parceria"):
    nome_familia = discord.ui.TextInput(
        label="Nome da Família",
        placeholder="Ex: Comando Vermelho",
        max_length=100,
    )
    produto = discord.ui.TextInput(
        label="Produto da Parceria",
        placeholder="Ex: Armamento, Munição, Veículos",
        max_length=100,
    )
    contato_01 = discord.ui.TextInput(
        label="Contato Principal",
        placeholder="Ex: João: (31) 99999-9999",
        required=False,
        max_length=150,
    )
    contato_02 = discord.ui.TextInput(
        label="Contato Secundário",
        placeholder="Ex: Pedro: (31) 98888-8888",
        required=False,
        max_length=150,
    )

    def __init__(self, repository: ParceriasRepository):
        super().__init__()
        self.repository = repository

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Sistema de parcerias indisponível.", ephemeral=True)
            return

        nome_familia = self.nome_familia.value.strip()
        produto = self.produto.value.strip()
        contato_01 = _optional_text(self.contato_01.value)
        contato_02 = _optional_text(self.contato_02.value)

        config = await self.repository.get_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message("Canal de parcerias ativas não configurado.", ephemeral=True)
            return

        active_channel = await resolve_text_channel(interaction.guild, config.parceria_ativas_channel_id)
        if not active_channel:
            await interaction.response.send_message("Canal de parcerias ativas não configurado.", ephemeral=True)
            return

        if await self.repository.find_by_name(interaction.guild.id, nome_familia):
            await interaction.response.send_message(
                "Essa família já possui parceria registrada. Use o botão Editar Parceria.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Dados recebidos! Envie agora a imagem do uniforme da família. Você tem **5 minutos**.",
            ephemeral=True,
        )
        upload = await collect_uniform_image(interaction, interaction.channel, interaction.user, nome_familia)
        if not upload:
            return

        file, filename = upload
        public_payload = {
            "nome_familia": nome_familia,
            "produto": produto,
            "contato_01": contato_01,
            "contato_02": contato_02,
            "criado_em": discord.utils.utcnow(),
        }
        try:
            public_message = await active_channel.send(
                embed=parceria_active_embed(public_payload, attachment_filename=filename),
                file=file,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            await interaction.followup.send("Não foi possível registrar a parceria.", ephemeral=True)
            return

        try:
            await self.repository.create_parceria(
                guild_id=interaction.guild.id,
                nome_familia=nome_familia,
                produto=produto,
                contato_01=contato_01,
                contato_02=contato_02,
                mensagem_lista_id=public_message.id,
                nome_arquivo_imagem=filename,
                registrado_por=interaction.user.id,
            )
        except (ParceriaDuplicadaError, httpx.HTTPError):
            try:
                await public_message.delete()
            except discord.HTTPException:
                pass
            await interaction.followup.send("Não foi possível registrar a parceria.", ephemeral=True)
            return

        await interaction.followup.send("Parceria registrada com sucesso.", ephemeral=True)


class ParceriaEditModal(discord.ui.Modal, title="Editar Parceria"):
    nome_familia = discord.ui.TextInput(label="Nome da Família", max_length=100)
    produto = discord.ui.TextInput(label="Produto da Parceria", max_length=100)
    contato_01 = discord.ui.TextInput(label="Contato Principal", required=False, max_length=150)
    contato_02 = discord.ui.TextInput(label="Contato Secundário", required=False, max_length=150)

    def __init__(self, repository: ParceriasRepository, parceria: dict):
        super().__init__()
        self.repository = repository
        self.parceria = parceria
        self.nome_familia.default = parceria["nome_familia"]
        self.produto.default = parceria["produto"]
        self.contato_01.default = parceria.get("contato_01") or ""
        self.contato_02.default = parceria.get("contato_02") or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Sistema de parcerias indisponível.", ephemeral=True)
            return

        nome_familia = self.nome_familia.value.strip()
        if await self.repository.name_exists_for_other(interaction.guild.id, nome_familia, self.parceria["id"]):
            await interaction.response.send_message(
                "Essa família já possui parceria registrada. Use o botão Editar Parceria.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.repository.update_details(
                parceria_id=self.parceria["id"],
                nome_familia=nome_familia,
                produto=self.produto.value.strip(),
                contato_01=_optional_text(self.contato_01.value),
                contato_02=_optional_text(self.contato_02.value),
            )
        except ParceriaDuplicadaError:
            await interaction.followup.send(
                "Essa família já possui parceria registrada. Use o botão Editar Parceria.", ephemeral=True
            )
            return
        except httpx.HTTPError:
            await interaction.followup.send("Sistema de parcerias indisponível.", ephemeral=True)
            return
        if not updated:
            await interaction.followup.send("Sistema de parcerias indisponível.", ephemeral=True)
            return

        public_message = await _fetch_public_message(interaction, self.repository, updated)
        if not public_message:
            await interaction.followup.send("Sistema de parcerias indisponível.", ephemeral=True)
            return

        image_url = _current_message_image_url(public_message)
        try:
            await public_message.edit(
                embed=parceria_active_embed(updated, image_url=image_url),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            await interaction.followup.send("Sistema de parcerias indisponível.", ephemeral=True)
            return

        await interaction.followup.send(
            "Deseja enviar uma nova imagem de uniforme?",
            view=ParceriaImageChoiceView(self.repository, updated["id"], interaction.user.id),
            ephemeral=True,
        )


class ParceriaActiveSelectView(discord.ui.View):
    def __init__(self, repository: ParceriasRepository, parcerias: list[dict], *, user_id: int, mode: str):
        super().__init__(timeout=180)
        self.repository = repository
        self.user_id = user_id
        self.mode = mode
        self.add_item(ParceriaActiveSelect(parcerias, mode=mode))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este painel privado pertence a outro usuário.", ephemeral=True)
            return False
        return True


class ParceriaActiveSelect(discord.ui.Select):
    def __init__(self, parcerias: list[dict], *, mode: str):
        options = [
            discord.SelectOption(
                label=parceria["nome_familia"][:100],
                description=parceria["produto"][:100],
                value=str(parceria["id"]),
            )
            for parceria in parcerias[:25]
        ]
        placeholder = "Selecione a parceria para editar" if mode == "edit" else "Selecione a parceria para remover"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ParceriaActiveSelectView):
            return
        parceria = await view.repository.get(int(self.values[0]))
        if not parceria or not parceria.get("ativo"):
            await interaction.response.send_message("Não há parcerias ativas cadastradas.", ephemeral=True)
            return
        if view.mode == "edit":
            await interaction.response.send_modal(ParceriaEditModal(view.repository, parceria))
            return
        await interaction.response.edit_message(
            content="Confirma a remoção dessa parceria?",
            view=ParceriaRemoveConfirmView(view.repository, parceria["id"], interaction.user.id),
        )


class ParceriaImageChoiceView(discord.ui.View):
    def __init__(self, repository: ParceriasRepository, parceria_id: int, user_id: int):
        super().__init__(timeout=300)
        self.repository = repository
        self.parceria_id = parceria_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este painel privado pertence a outro usuário.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sim", style=discord.ButtonStyle.primary)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Sistema de parcerias indisponível.", ephemeral=True)
            return
        parceria = await self.repository.get(self.parceria_id)
        if not parceria:
            await interaction.response.send_message("Sistema de parcerias indisponível.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content="Envie a nova imagem do uniforme neste canal. Você tem **5 minutos**.",
            view=None,
        )
        upload = await collect_uniform_image(interaction, interaction.channel, interaction.user, parceria["nome_familia"])
        if not upload:
            return
        file, filename = upload

        public_message = await _fetch_public_message(interaction, self.repository, parceria)
        if not public_message:
            await interaction.followup.send("Sistema de parcerias indisponível.", ephemeral=True)
            return

        updated_payload = dict(parceria)
        updated_payload["nome_arquivo_imagem"] = filename
        try:
            await public_message.edit(
                embed=parceria_active_embed(updated_payload, attachment_filename=filename),
                attachments=[file],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            await interaction.followup.send("Sistema de parcerias indisponível.", ephemeral=True)
            return

        await self.repository.update_image(parceria_id=self.parceria_id, nome_arquivo_imagem=filename)
        await interaction.followup.send("Parceria atualizada com nova imagem.", ephemeral=True)

    @discord.ui.button(label="Não", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Parceria atualizada mantendo a imagem atual.", view=None)


class ParceriaRemoveConfirmView(discord.ui.View):
    def __init__(self, repository: ParceriasRepository, parceria_id: int, user_id: int):
        super().__init__(timeout=180)
        self.repository = repository
        self.parceria_id = parceria_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este painel privado pertence a outro usuário.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        parceria = await self.repository.get(self.parceria_id)
        if parceria:
            public_message = await _fetch_public_message(interaction, self.repository, parceria)
            if public_message:
                try:
                    await public_message.delete()
                except discord.HTTPException:
                    pass
            await self.repository.deactivate(self.parceria_id)
        await interaction.response.edit_message(content="Parceria removida da lista ativa.", view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Remoção cancelada.", view=None)


async def _send_active_select(interaction: discord.Interaction, repository: ParceriasRepository, *, mode: str) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Sistema de parcerias indisponível.", ephemeral=True)
        return
    parcerias = await repository.list_active(interaction.guild.id)
    if not parcerias:
        await interaction.response.send_message("Não há parcerias ativas cadastradas.", ephemeral=True)
        return
    view = ParceriaActiveSelectView(repository, parcerias, user_id=interaction.user.id, mode=mode)
    label = "editar" if mode == "edit" else "remover"
    await interaction.response.send_message(f"Selecione a parceria que deseja {label}.", view=view, ephemeral=True)


async def collect_uniform_image(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    member: discord.Member,
    nome_familia: str,
) -> tuple[discord.File, str] | None:
    previous_overwrite, had_previous_overwrite, changed_permissions = await _allow_temporary_upload(channel, member)
    deadline = asyncio.get_running_loop().time() + 300
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                await interaction.followup.send("Tempo esgotado, registro cancelado. Tente novamente.", ephemeral=True)
                return None
            try:
                message = await interaction.client.wait_for(
                    "message",
                    check=lambda candidate: candidate.author.id == member.id and candidate.channel.id == channel.id,
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                await interaction.followup.send("Tempo esgotado, registro cancelado. Tente novamente.", ephemeral=True)
                return None

            attachment = next(
                (
                    item
                    for item in message.attachments
                    if is_valid_image_attachment(item.filename, getattr(item, "content_type", None))
                ),
                None,
            )
            if not attachment:
                await interaction.followup.send("Não encontrei uma imagem válida, envie novamente.", ephemeral=True)
                continue

            filename = uniform_filename(nome_familia, attachment.filename, getattr(attachment, "content_type", None))
            try:
                data = await attachment.read()
            except discord.HTTPException:
                await interaction.followup.send("Não consegui baixar a imagem enviada. Tente novamente.", ephemeral=True)
                return None

            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return discord.File(io.BytesIO(data), filename=filename), filename
    finally:
        if changed_permissions:
            await _restore_temporary_upload(channel, member, previous_overwrite, had_previous_overwrite)


async def _allow_temporary_upload(
    channel: discord.TextChannel,
    member: discord.Member,
) -> tuple[discord.PermissionOverwrite, bool, bool]:
    previous = channel.overwrites_for(member)
    had_previous = not previous.is_empty()
    overwrite = discord.PermissionOverwrite.from_pair(*previous.pair())
    overwrite.send_messages = True
    overwrite.attach_files = True
    overwrite.read_message_history = True
    try:
        await channel.set_permissions(member, overwrite=overwrite, reason="Yuno parcerias: envio temporário de uniforme")
    except discord.HTTPException:
        return previous, had_previous, False
    return previous, had_previous, True


async def _restore_temporary_upload(
    channel: discord.TextChannel,
    member: discord.Member,
    previous: discord.PermissionOverwrite,
    had_previous: bool,
) -> None:
    try:
        if had_previous:
            await channel.set_permissions(member, overwrite=previous, reason="Yuno parcerias: remover envio temporário de uniforme")
        else:
            await channel.set_permissions(member, overwrite=None, reason="Yuno parcerias: remover envio temporário de uniforme")
    except discord.HTTPException:
        pass


async def _fetch_public_message(
    interaction: discord.Interaction,
    repository: ParceriasRepository,
    parceria: dict,
) -> discord.Message | None:
    if not interaction.guild:
        return None
    config = await repository.get_config(interaction.guild.id)
    if not config:
        return None
    active_channel = await resolve_text_channel(interaction.guild, config.parceria_ativas_channel_id)
    if not active_channel:
        return None
    try:
        return await active_channel.fetch_message(int(parceria["mensagem_lista_id"]))
    except (ValueError, discord.HTTPException):
        return None


def _current_message_image_url(message: discord.Message) -> str | None:
    if message.attachments:
        return message.attachments[0].url
    if message.embeds and message.embeds[0].image:
        return message.embeds[0].image.url
    return None


def _optional_text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None
