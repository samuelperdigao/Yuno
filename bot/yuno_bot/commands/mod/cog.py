import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.mod.helpers import SEPARADOR_CANAIS, eh_categoria_visual, nome_com_separador
from yuno_bot.commands.shared import get_guild_config
from yuno_bot.guards import deny, ensure_allowed


async def _proteger_categoria_visual(category: discord.CategoryChannel) -> bool:
    """Torna o divisor visivel e impede @everyone de gerencia-lo."""
    if not eh_categoria_visual(category.name):
        return False
    overwrite = category.overwrites_for(category.guild.default_role)
    if overwrite.view_channel is True and overwrite.manage_channels is False:
        return False
    overwrite.view_channel = True
    overwrite.manage_channels = False
    await category.set_permissions(category.guild.default_role, overwrite=overwrite, reason="Yuno: protecao da categoria visual")
    return True


class ModCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    mod = app_commands.Group(name="mod", description="Comandos de moderacao")

    async def _modulo_ligado(self, guild_id: int) -> bool:
        config = await get_guild_config(self.bot.api, guild_id)
        return bool((config.get("modules") or {}).get("mod", False))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            if not await self._modulo_ligado(guild.id):
                continue
            for category in guild.categories:
                try:
                    await _proteger_categoria_visual(category)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, discord.CategoryChannel):
            return
        if not await self._modulo_ligado(channel.guild.id):
            return
        try:
            await _proteger_categoria_visual(channel)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @mod.command(name="limpar", description="Apaga mensagens do canal atual")
    @app_commands.describe(quantidade="Numero de mensagens a apagar (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def limpar(self, interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100]) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "mod", "limpar")
        if not allowed:
            await deny(interaction, reason)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await deny(interaction, "use dentro de um canal de texto.")
            return

        await interaction.response.defer(ephemeral=True)
        try:
            deletadas = await interaction.channel.purge(limit=quantidade)
            await interaction.followup.send(f"{len(deletadas)} mensagem(ns) apagada(s).", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Sem permissão para apagar mensagens neste canal.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Erro ao apagar mensagens.", ephemeral=True)

    @limpar.error
    async def limpar_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Você precisa da permissão **Gerenciar Mensagens** para usar este comando.", ephemeral=True)
        elif not interaction.response.is_done():
            await interaction.response.send_message("Erro inesperado.", ephemeral=True)

    @mod.command(name="organizar_canais", description="Adiciona o separador visual nos canais de texto que ainda nao tem")
    @app_commands.describe(
        categoria="Categoria que sera organizada. Se vazio, usa a categoria atual.",
        todos="Organizar todos os canais de texto do servidor.",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def organizar_canais(
        self,
        interaction: discord.Interaction,
        categoria: discord.CategoryChannel | None = None,
        todos: bool = False,
    ) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "mod", "organizar_canais")
        if not allowed:
            await deny(interaction, reason)
            return
        if not interaction.guild:
            await deny(interaction, "use dentro de um servidor.")
            return

        await interaction.response.defer(ephemeral=True)

        if todos:
            canais = list(interaction.guild.text_channels)
            escopo = "servidor inteiro"
        else:
            categoria_alvo = categoria or getattr(interaction.channel, "category", None)
            if categoria_alvo is None:
                await interaction.followup.send("Informe uma categoria ou use `todos: True`.", ephemeral=True)
                return
            canais = list(categoria_alvo.text_channels)
            escopo = f"categoria **{categoria_alvo.name}**"

        renomeados: list[str] = []
        ignorados = 0
        falhas: list[str] = []

        for canal in sorted(canais, key=lambda ch: ch.position):
            novo_nome = nome_com_separador(canal.name)
            if novo_nome is None:
                ignorados += 1
                continue
            nome_antigo = canal.name
            try:
                await canal.edit(name=novo_nome, reason=f"Yuno: organizacao de canais solicitada por {interaction.user}")
                renomeados.append(f"`#{nome_antigo}` → `#{novo_nome}`")
            except discord.Forbidden:
                falhas.append(f"`#{nome_antigo}` (sem permissão)")
            except discord.HTTPException as exc:
                falhas.append(f"`#{nome_antigo}` ({exc})")

        descricao = (
            f"Escopo: {escopo}\n"
            f"Renomeados: `{len(renomeados)}`\n"
            f"Já tinham `{SEPARADOR_CANAIS}`: `{ignorados}`\n"
            f"Falhas: `{len(falhas)}`"
        )
        embed = discord.Embed(
            title="Canais organizados",
            description=descricao,
            color=discord.Color.green() if not falhas else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )
        if renomeados:
            embed.add_field(name="Alterados", value="\n".join(renomeados[:10]), inline=False)
        if len(renomeados) > 10:
            embed.add_field(name="Mais alterações", value=f"`{len(renomeados) - 10}` canal(is) além dos listados.", inline=False)
        if falhas:
            embed.add_field(name="Falhas", value="\n".join(falhas[:10]), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @organizar_canais.error
    async def organizar_canais_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Você precisa da permissão **Gerenciar Canais** para usar este comando.", ephemeral=True)
        elif not interaction.response.is_done():
            await interaction.response.send_message("Erro inesperado.", ephemeral=True)
