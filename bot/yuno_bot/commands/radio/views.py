import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.radio.modals import RadioModal
from yuno_bot.guards import deny, requires_module


def _tem_permissao_de_gerenciar(member: discord.abc.User, guild: discord.Guild | None) -> bool:
    if not isinstance(member, discord.Member) or guild is None:
        return False
    perms = member.guild_permissions
    return perms.manage_guild or perms.administrator or guild.owner_id == member.id


class RadioPanelView(discord.ui.View):
    """Painel fixo com um unico botao. `command_permissions["radio.definir"]`
    permite restringir por cargo/canal via dashboard; a exigencia de "gerenciar
    servidor" do produto MDM e nativa do Discord e checada aqui, nao pelo
    `command_permissions` (que por padrao libera qualquer cargo)."""

    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(
        label="Definir Nova Rádio",
        emoji="📻",
        style=discord.ButtonStyle.primary,
        custom_id="yuno:radio:panel:definir",
    )
    @requires_module("radio", "definir")
    async def definir(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not _tem_permissao_de_gerenciar(interaction.user, interaction.guild):
            await deny(interaction, "você precisa ter permissão de gerenciar servidor.")
            return
        await interaction.response.send_modal(RadioModal(self.api))
