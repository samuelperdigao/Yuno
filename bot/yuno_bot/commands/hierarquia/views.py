import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.hierarquia.embeds import (
    hierarquia_confirmation_embed,
    hierarquia_log_embed,
    hierarquia_select_cargo_embed,
)
from yuno_bot.commands.hierarquia.helpers import cargo_atual, tipo_mudanca
from yuno_bot.commands.shared import create_record, get_guild_config, send_module_log
from yuno_bot.guards import requires_module

COR_HIERARQUIA = discord.Color.from_rgb(255, 215, 0)


def resolve_ladder_roles(guild: discord.Guild, config: dict, key: str = "role_ids") -> list[discord.Role]:
    ids = ((config.get("settings") or {}).get("hierarquia") or {}).get(key) or []
    roles = [guild.get_role(int(role_id)) for role_id in ids]
    return [role for role in roles if role is not None]


def _cargo_atual_role(membro: discord.Member, ladder_roles: list[discord.Role]) -> discord.Role | None:
    ladder_ids = [role.id for role in ladder_roles]
    resultado_id = cargo_atual([role.id for role in membro.roles], ladder_ids)
    if resultado_id is None:
        return None
    return next((role for role in ladder_roles if role.id == resultado_id), None)


class _CargoSelect(discord.ui.Select):
    def __init__(self, ladder_roles: list[discord.Role]) -> None:
        options = [discord.SelectOption(label=role.name, value=str(role.id)) for role in ladder_roles[:25]]
        super().__init__(placeholder="Selecione o novo cargo...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, CargoSelectView):
            return
        await view.apply_cargo(interaction, novo_cargo_id=int(self.values[0]))


class CargoSelectView(discord.ui.View):
    def __init__(self, api: YunoAPI, *, executor_id: int, membro_alvo: discord.Member, ladder_roles: list[discord.Role]) -> None:
        super().__init__(timeout=120)
        self.api = api
        self.executor_id = executor_id
        self.membro_alvo = membro_alvo
        self.ladder_roles = ladder_roles
        self.add_item(_CargoSelect(ladder_roles))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.executor_id:
            await interaction.response.send_message("Apenas quem iniciou pode usar este menu.", ephemeral=True)
            return False
        return True

    async def apply_cargo(self, interaction: discord.Interaction, *, novo_cargo_id: int) -> None:
        guild = interaction.guild
        if not guild:
            return
        novo_cargo = guild.get_role(novo_cargo_id)
        if novo_cargo is None:
            await interaction.response.send_message("Cargo não encontrado neste servidor.", ephemeral=True)
            return

        ladder_ids = [role.id for role in self.ladder_roles]
        cargo_anterior_id = cargo_atual([role.id for role in self.membro_alvo.roles], ladder_ids)
        cargo_anterior_role = next((role for role in self.ladder_roles if role.id == cargo_anterior_id), None)
        tipo = tipo_mudanca(ladder_ids, cargo_anterior_id, novo_cargo_id)

        cargos_para_remover = [role for role in self.membro_alvo.roles if role.id in ladder_ids]
        try:
            if cargos_para_remover:
                await self.membro_alvo.remove_roles(*cargos_para_remover, reason=f"Yuno hierarquia por {interaction.user}")
            await self.membro_alvo.add_roles(novo_cargo, reason=f"Yuno hierarquia por {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("Sem permissão para alterar cargos deste membro.", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("Erro ao aplicar o cargo.", ephemeral=True)
            return

        payload = {
            "membro_id": str(self.membro_alvo.id),
            "cargo_anterior_id": str(cargo_anterior_id) if cargo_anterior_id else None,
            "cargo_novo_id": str(novo_cargo_id),
            "tipo": tipo,
        }
        try:
            record = await create_record(
                self.api, interaction, module="hierarquia", title=f"Hierarquia: {self.membro_alvo.display_name}", payload=payload
            )
        except httpx.HTTPError:
            record = None

        await interaction.response.edit_message(
            embed=hierarquia_confirmation_embed(self.membro_alvo, cargo_anterior_role, novo_cargo, tipo), view=None
        )
        if record:
            await send_module_log(
                self.api,
                interaction,
                "hierarquia",
                hierarquia_log_embed(interaction, record, self.membro_alvo, cargo_anterior_role, novo_cargo, tipo),
            )


class MembroSelectView(discord.ui.View):
    def __init__(self, api: YunoAPI, *, executor_id: int, ladder_roles: list[discord.Role]) -> None:
        super().__init__(timeout=120)
        self.api = api
        self.executor_id = executor_id
        self.ladder_roles = ladder_roles

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.executor_id:
            await interaction.response.send_message("Apenas quem iniciou pode usar este menu.", ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Selecione o membro...", min_values=1, max_values=1)
    async def selecionar_membro(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        membro = select.values[0]
        if not isinstance(membro, discord.Member):
            await interaction.response.send_message("Membro não encontrado neste servidor.", ephemeral=True)
            return
        embed = hierarquia_select_cargo_embed(membro, _cargo_atual_role(membro, self.ladder_roles))
        view = CargoSelectView(self.api, executor_id=self.executor_id, membro_alvo=membro, ladder_roles=self.ladder_roles)
        await interaction.response.edit_message(embed=embed, view=view)


class HierarquiaPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Gerenciar Hierarquia", style=discord.ButtonStyle.primary, custom_id="yuno:hierarquia:panel:gerenciar")
    @requires_module("hierarquia", "gerenciar")
    async def gerenciar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return
        config = await get_guild_config(self.api, interaction.guild.id)
        ladder_roles = resolve_ladder_roles(interaction.guild, config)
        if not ladder_roles:
            await interaction.response.send_message(
                "Hierarquia ainda não configurada. Peça a um admin para rodar `/hierarquia painel`.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="👑 Gerenciar Hierarquia", description="Selecione o membro que deseja promover ou rebaixar:", color=COR_HIERARQUIA
        )
        view = MembroSelectView(self.api, executor_id=interaction.user.id, ladder_roles=ladder_roles)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
