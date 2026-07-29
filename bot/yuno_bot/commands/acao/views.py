import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.acao.embeds import (
    pagamento_embed,
    regras_embed,
    resultado_embed,
    selecionar_acao_embed,
)
from yuno_bot.commands.acao.helpers import acao_id_from_message, find_tipo
from yuno_bot.commands.shared import channel_id_from_setup, create_record, get_guild_config, resolve_text_channel
from yuno_bot.guards import requires_module

POR_PAGINA = 20


async def _resolve(api: YunoAPI, interaction: discord.Interaction) -> tuple[dict, dict] | None:
    """Resolve (record, tipo_dict) a partir da mensagem clicada, ou responde
    com o erro e devolve None."""
    acao_id = acao_id_from_message(interaction.message)
    if not acao_id:
        await interaction.response.send_message("Não consegui identificar esta ação.", ephemeral=True)
        return None
    try:
        record = await api.get_record(module="acao", record_id=acao_id)
    except httpx.HTTPError:
        await interaction.response.send_message("Não consegui carregar esta ação.", ephemeral=True)
        return None
    if record["status"] != "open":
        await interaction.response.send_message("Esta ação já foi finalizada.", ephemeral=True)
        return None
    config = await get_guild_config(api, interaction.guild_id)
    tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
    tipo_dict = find_tipo(tipos, record["payload"]["acao_key"])
    if not tipo_dict:
        await interaction.response.send_message("O tipo desta ação não existe mais no catálogo.", ephemeral=True)
        return None
    return record, tipo_dict


async def finalize_acao(
    api: YunoAPI,
    interaction: discord.Interaction,
    *,
    acao_id: int,
    resultado: str,
    observacao: str | None,
    pagamento: dict,
) -> None:
    record = await api.get_record(module="acao", record_id=acao_id)
    config = await get_guild_config(api, interaction.guild_id)
    tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
    tipo_dict = find_tipo(tipos, record["payload"]["acao_key"]) or {"nome": record["payload"]["acao_key"], "emoji": "⚡"}
    participantes = record["payload"].get("participantes") or []

    payload_patch = {
        "resultado": resultado,
        "observacao": observacao,
        "finalizado_por": str(interaction.user.id),
        **pagamento,
    }
    updated = await api.patch_record(module="acao", record_id=acao_id, status="done", reviewer_id=interaction.user.id, payload=payload_patch)

    destino_key = "acao_ganhas" if resultado == "ganha" else "acao_perdidas"
    canal_resultado = await resolve_text_channel(interaction.guild, channel_id_from_setup(config, destino_key))
    sent_result = False
    if canal_resultado:
        try:
            await canal_resultado.send(embed=resultado_embed(tipo_dict, updated, participantes))
            sent_result = True
        except discord.HTTPException:
            pass

    sent_payment = True
    if resultado == "ganha":
        sent_payment = False
        canal_pagamento = await resolve_text_channel(interaction.guild, channel_id_from_setup(config, "acao_pagamento"))
        if canal_pagamento:
            try:
                await canal_pagamento.send(embed=pagamento_embed(tipo_dict, updated, participantes))
                sent_payment = True
            except discord.HTTPException:
                pass

    try:
        if interaction.message:
            await interaction.message.delete()
    except discord.HTTPException:
        pass

    avisos = []
    if not sent_result:
        avisos.append("canal de resultado não configurado")
    if not sent_payment:
        avisos.append("canal de pagamento não configurado")
    extra = f" ⚠️ {'; '.join(avisos)}." if avisos else ""
    await interaction.followup.send(f"Ação finalizada como {'ganha' if resultado == 'ganha' else 'perdida'}.{extra}", ephemeral=True)


class AcaoParticipantesView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="✅ Entrar na ação", style=discord.ButtonStyle.success, custom_id="yuno:acao:entrar")
    @requires_module("acao", "participar")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await _resolve(self.api, interaction)
        if not resolved:
            return
        record, tipo_dict = resolved
        participantes = list(record["payload"].get("participantes") or [])
        if any(p["user_id"] == str(interaction.user.id) for p in participantes):
            await interaction.response.send_message("Você já está inscrito nesta ação.", ephemeral=True)
            return
        max_p = tipo_dict.get("max_participantes")
        if max_p and len(participantes) >= max_p:
            await interaction.response.send_message(f"Vagas esgotadas (máximo: {max_p}).", ephemeral=True)
            return
        participantes.append({"user_id": str(interaction.user.id), "nome": interaction.user.display_name, "origem": "self"})
        updated = await self.api.patch_record(
            module="acao", record_id=record["id"], status="open", reviewer_id=interaction.user.id, payload={"participantes": participantes}
        )
        await interaction.response.edit_message(embed=regras_embed(tipo_dict, updated, participantes), view=self)

    @discord.ui.button(label="🚪 Sair da ação", style=discord.ButtonStyle.danger, custom_id="yuno:acao:sair")
    @requires_module("acao", "participar")
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await _resolve(self.api, interaction)
        if not resolved:
            return
        record, tipo_dict = resolved
        participantes = list(record["payload"].get("participantes") or [])
        if not any(p["user_id"] == str(interaction.user.id) for p in participantes):
            await interaction.response.send_message("Você não está inscrito nesta ação.", ephemeral=True)
            return
        participantes = [p for p in participantes if p["user_id"] != str(interaction.user.id)]
        updated = await self.api.patch_record(
            module="acao", record_id=record["id"], status="open", reviewer_id=interaction.user.id, payload={"participantes": participantes}
        )
        await interaction.response.edit_message(embed=regras_embed(tipo_dict, updated, participantes), view=self)

    @discord.ui.button(label="➕ Adicionar membro", style=discord.ButtonStyle.secondary, custom_id="yuno:acao:adicionar")
    @requires_module("acao", "gerenciar")
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await _resolve(self.api, interaction)
        if not resolved:
            return
        record, _tipo_dict = resolved
        if not interaction.guild:
            return
        inscritos = {p["user_id"] for p in record["payload"].get("participantes") or []}
        membros = sorted(
            (member for member in interaction.guild.members if not member.bot and str(member.id) not in inscritos),
            key=lambda member: member.display_name.lower(),
        )
        if not membros:
            await interaction.response.send_message("Nenhum membro disponível para adicionar.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Selecione o membro para adicionar à ação:",
            view=AdicionarMembroPaginadoView(self.api, acao_id=record["id"], membros=membros, painel_message=interaction.message),
            ephemeral=True,
        )

    @discord.ui.button(label="➖ Remover membro", style=discord.ButtonStyle.secondary, custom_id="yuno:acao:remover")
    @requires_module("acao", "gerenciar")
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await _resolve(self.api, interaction)
        if not resolved:
            return
        record, _tipo_dict = resolved
        participantes = record["payload"].get("participantes") or []
        if not participantes:
            await interaction.response.send_message("Nenhum membro inscrito para remover.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Selecione o membro que deseja remover da ação:",
            view=RemoverMembroView(self.api, acao_id=record["id"], participantes=participantes, painel_message=interaction.message),
            ephemeral=True,
        )

    @discord.ui.button(label="🔒 Finalizar ação", style=discord.ButtonStyle.danger, custom_id="yuno:acao:finalizar", row=1)
    @requires_module("acao", "gerenciar")
    async def finalizar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await _resolve(self.api, interaction)
        if not resolved:
            return
        record, _tipo_dict = resolved
        participantes_count = len(record["payload"].get("participantes") or [])
        from yuno_bot.commands.acao.modals import FinalizarAcaoModal

        await interaction.response.send_modal(FinalizarAcaoModal(self.api, record["id"], participantes_count))


class AdicionarMembroPaginadoView(discord.ui.View):
    def __init__(
        self,
        api: YunoAPI,
        *,
        acao_id: int,
        membros: list[discord.Member],
        painel_message: discord.Message | None,
        pagina: int = 0,
    ) -> None:
        super().__init__(timeout=60)
        self.api = api
        self.acao_id = acao_id
        self.membros = membros
        self.painel_message = painel_message
        self.pagina = pagina
        self._rebuild()

    def _total_paginas(self) -> int:
        return max(1, (len(self.membros) + POR_PAGINA - 1) // POR_PAGINA)

    def _rebuild(self) -> None:
        self.clear_items()
        inicio = self.pagina * POR_PAGINA
        fatia = self.membros[inicio : inicio + POR_PAGINA]
        select = discord.ui.Select(
            placeholder=f"Membros (pág. {self.pagina + 1}/{self._total_paginas()})...",
            options=[discord.SelectOption(label=member.display_name[:100], value=str(member.id)) for member in fatia],
        )
        select.callback = self._on_select
        self.add_item(select)
        if self._total_paginas() > 1:
            anterior = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.pagina == 0)
            anterior.callback = self._anterior
            self.add_item(anterior)
            proxima = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.pagina >= self._total_paginas() - 1)
            proxima.callback = self._proxima
            self.add_item(proxima)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        try:
            record = await self.api.get_record(module="acao", record_id=self.acao_id)
        except httpx.HTTPError:
            await interaction.response.edit_message(content="Não consegui carregar esta ação.", view=None)
            return
        if record["status"] != "open":
            await interaction.response.edit_message(content="Esta ação já foi finalizada.", view=None)
            return

        member_id = int(interaction.data["values"][0])
        member = interaction.guild.get_member(member_id) if interaction.guild else None
        if member is None:
            await interaction.response.edit_message(content="Membro não encontrado no servidor.", view=None)
            return

        config = await get_guild_config(self.api, interaction.guild_id)
        tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
        tipo_dict = find_tipo(tipos, record["payload"]["acao_key"])
        participantes = list(record["payload"].get("participantes") or [])
        if any(p["user_id"] == str(member.id) for p in participantes):
            await interaction.response.edit_message(content=f"{member.display_name} já está inscrito.", view=None)
            return
        max_p = tipo_dict.get("max_participantes") if tipo_dict else None
        if max_p and len(participantes) >= max_p:
            await interaction.response.edit_message(content=f"Vagas esgotadas (máximo: {max_p}).", view=None)
            return

        participantes.append({"user_id": str(member.id), "nome": member.display_name, "origem": "lideranca"})
        updated = await self.api.patch_record(
            module="acao", record_id=self.acao_id, status="open", reviewer_id=interaction.user.id, payload={"participantes": participantes}
        )
        await interaction.response.edit_message(content=f"{member.mention} adicionado à ação!", view=None)
        if tipo_dict and self.painel_message:
            try:
                await self.painel_message.edit(embed=regras_embed(tipo_dict, updated, participantes), view=AcaoParticipantesView(self.api))
            except discord.HTTPException:
                pass

    async def _anterior(self, interaction: discord.Interaction) -> None:
        self.pagina -= 1
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _proxima(self, interaction: discord.Interaction) -> None:
        self.pagina += 1
        self._rebuild()
        await interaction.response.edit_message(view=self)


class RemoverMembroView(discord.ui.View):
    def __init__(self, api: YunoAPI, *, acao_id: int, participantes: list[dict], painel_message: discord.Message | None) -> None:
        super().__init__(timeout=60)
        self.api = api
        self.acao_id = acao_id
        self.painel_message = painel_message
        select = discord.ui.Select(
            placeholder="Selecione o membro para remover...",
            options=[
                discord.SelectOption(label=(p.get("nome") or p["user_id"])[:100], value=p["user_id"])
                for p in participantes[:25]
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        try:
            record = await self.api.get_record(module="acao", record_id=self.acao_id)
        except httpx.HTTPError:
            await interaction.response.edit_message(content="Não consegui carregar esta ação.", view=None)
            return
        if record["status"] != "open":
            await interaction.response.edit_message(content="Esta ação já foi finalizada.", view=None)
            return

        member_id = interaction.data["values"][0]
        participantes = [p for p in (record["payload"].get("participantes") or []) if p["user_id"] != member_id]
        updated = await self.api.patch_record(
            module="acao", record_id=self.acao_id, status="open", reviewer_id=interaction.user.id, payload={"participantes": participantes}
        )
        await interaction.response.edit_message(content=f"<@{member_id}> removido da ação.", view=None)

        config = await get_guild_config(self.api, interaction.guild_id)
        tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
        tipo_dict = find_tipo(tipos, record["payload"]["acao_key"])
        if tipo_dict and self.painel_message:
            try:
                await self.painel_message.edit(embed=regras_embed(tipo_dict, updated, participantes), view=AcaoParticipantesView(self.api))
            except discord.HTTPException:
                pass


class AcaoSelectView(discord.ui.View):
    def __init__(self, api: YunoAPI, *, horario: str, tipo: str, data: str, tipos: list[dict]) -> None:
        super().__init__(timeout=120)
        self.api = api
        self.horario = horario
        self.tipo = tipo
        self.data = data
        options = [discord.SelectOption(label=item["nome"], value=item["key"], emoji=item.get("emoji") or None) for item in tipos[:25]]
        select = discord.ui.Select(placeholder="Escolha a ação...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        acao_key = interaction.data["values"][0]
        payload = {
            "acao_key": acao_key,
            "tipo": self.tipo,
            "data": self.data,
            "horario": self.horario,
            "participantes": [],
            "resultado": None,
            "observacao": None,
        }
        record = await create_record(self.api, interaction, module="acao", title=f"Ação: {acao_key}", payload=payload)

        config = await get_guild_config(self.api, interaction.guild_id)
        tipos = ((config.get("settings") or {}).get("acao") or {}).get("tipos") or []
        tipo_dict = find_tipo(tipos, acao_key) or {"key": acao_key, "nome": acao_key, "emoji": "⚡", "max_participantes": None, "regras": ""}

        await interaction.response.send_message(embed=regras_embed(tipo_dict, record, []), view=AcaoParticipantesView(self.api))
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass


class AcaoTipoView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=60)
        self.api = api

    async def _abrir_modal(self, interaction: discord.Interaction, tipo: str) -> None:
        from yuno_bot.commands.acao.modals import IniciarAcaoModal

        await interaction.response.send_modal(IniciarAcaoModal(self.api, tipo))

    @discord.ui.button(label="Fuga", emoji="🏃", style=discord.ButtonStyle.primary)
    async def fuga(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._abrir_modal(interaction, "fuga")

    @discord.ui.button(label="No Tiro", emoji="🔫", style=discord.ButtonStyle.danger)
    async def tiro(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._abrir_modal(interaction, "tiro")


class AcaoPainelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="⚡ Iniciar Ação", style=discord.ButtonStyle.primary, custom_id="yuno:acao:panel:iniciar")
    @requires_module("acao", "gerenciar")
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Escolha o tipo da ação:", view=AcaoTipoView(self.api), ephemeral=True)
