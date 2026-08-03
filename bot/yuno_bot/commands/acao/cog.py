import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.acao.embeds import catalogo_listagem_embed, painel_fixo_embed
from yuno_bot.commands.acao.helpers import remove_tipo
from yuno_bot.commands.acao.modals import TipoRegrasModal
from yuno_bot.commands.acao.views import AcaoPainelView, AcaoTipoView
from yuno_bot.commands.panels import publish_or_update_panel, remove_previous_panel, rollback_unsaved_panel, with_panel_config
from yuno_bot.guards import deny, ensure_allowed


class AcaoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    acao = app_commands.Group(name="acao", description="Sistema de ações")

    @acao.command(name="iniciar", description="Abre o seletor de tipo de ação (fuga ou tiro)")
    async def iniciar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "acao", "gerenciar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_message("Escolha o tipo da ação:", view=AcaoTipoView(self.bot.api), ephemeral=True)

    @acao.command(name="tipo_criar", description="Cadastra ou atualiza um tipo de acao no catalogo")
    @app_commands.describe(
        chave="Identificador curto (ex: banco_central), sem espacos",
        nome="Nome exibido (ex: Banco Central)",
        emoji="Emoji do tipo (ex: 🏦)",
        max_participantes="Numero maximo de participantes, vazio para sem limite",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def tipo_criar(
        self,
        interaction: discord.Interaction,
        chave: str,
        nome: str,
        emoji: str,
        max_participantes: int | None = None,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return

        chave_normalizada = chave.strip().lower().replace(" ", "_")
        if not chave_normalizada or not nome.strip() or not emoji.strip():
            await interaction.response.send_message("Informe chave, nome e emoji validos.", ephemeral=True)
            return
        if max_participantes is not None and max_participantes <= 0:
            await interaction.response.send_message("`max_participantes` precisa ser maior que zero, ou vazio para sem limite.", ephemeral=True)
            return

        await interaction.response.send_modal(
            TipoRegrasModal(self.bot.api, chave=chave_normalizada, nome=nome.strip(), emoji=emoji.strip(), max_participantes=max_participantes)
        )

    @acao.command(name="tipo_remover", description="Remove um tipo de acao do catalogo")
    @app_commands.default_permissions(manage_guild=True)
    async def tipo_remover(self, interaction: discord.Interaction, chave: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            config = await self.bot.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
                return
            await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
            return

        settings = dict(config.get("settings") or {})
        acao_settings = dict(settings.get("acao") or {})
        tipos = remove_tipo(list(acao_settings.get("tipos") or []), chave.strip().lower())
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
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui salvar o catalogo de acoes.", ephemeral=True)
            return
        await interaction.followup.send("Tipo removido do catalogo (se existia).", ephemeral=True)

    @acao.command(name="tipo_listar", description="Lista os tipos de acao cadastrados")
    async def tipo_listar(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await deny(interaction, "use dentro de um servidor.")
            return
        await interaction.response.defer(ephemeral=True)
        try:
            config = await self.bot.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
            return
        tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
        await interaction.followup.send(embed=catalogo_listagem_embed(tipos), ephemeral=True)

    @acao.command(name="painel", description="Publica ou atualiza o painel fixo de acao e define os cargos gerentes")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(self, interaction: discord.Interaction, canal: discord.TextChannel, cargos_gerentes: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return

        from yuno_bot.commands.farm_tickets.helpers import parse_discord_ids

        role_ids = parse_discord_ids(cargos_gerentes)
        roles = [interaction.guild.get_role(role_id) for role_id in role_ids]
        if not role_ids or any(role is None for role in roles):
            await interaction.response.send_message("Informe cargos validos em `cargos_gerentes`.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            current_config = await self.bot.api.get_guild_config(interaction.guild.id, force=True)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
                return
            await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
            return

        panel_message = await publish_or_update_panel(
            canal,
            current_config,
            module_key="acao",
            embed=painel_fixo_embed(),
            view=AcaoPainelView(self.bot.api),
        )
        if panel_message is None:
            await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
            return

        updated_config = with_panel_config(
            current_config,
            module_key="acao",
            channel_id=canal.id,
            message_id=panel_message.id,
            command_names=("gerenciar",),
        )
        command_permissions = dict(updated_config.get("command_permissions") or {})
        rule = dict(command_permissions.get("acao.gerenciar") or {})
        rule["role_ids"] = [str(role_id) for role_id in role_ids]
        command_permissions["acao.gerenciar"] = rule
        updated_config["command_permissions"] = command_permissions
        acao_settings = dict(updated_config["settings"].get("acao") or {})
        acao_settings["manager_role_ids"] = [str(role_id) for role_id in role_ids]
        updated_config["settings"]["acao"] = acao_settings
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await rollback_unsaved_panel(current_config, panel_message, module_key="acao")
            await interaction.followup.send("Painel publicado, mas nao consegui salvar os cargos gerentes.", ephemeral=True)
            return

        await remove_previous_panel(
            current_config,
            canal,
            module_key="acao",
            message_id=panel_message.id,
        )
        cargos_txt = " ".join(role.mention for role in roles)
        await interaction.followup.send(f"Painel de ação publicado em {canal.mention}.\nGerentes: {cargos_txt}", ephemeral=True)
