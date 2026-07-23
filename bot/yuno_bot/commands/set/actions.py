import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.set.embeds import approval_log_embed, rejection_log_embed
from yuno_bot.commands.shared import send_module_log


async def approve_set_record(api: YunoAPI, interaction: discord.Interaction, protocolo: int) -> tuple[dict | None, str]:
    try:
        record = await api.patch_record(module="set", record_id=protocolo, status="approved", reviewer_id=interaction.user.id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, "Solicitacao de set nao encontrada."
        return None, "Nao consegui aprovar este set agora."
    except httpx.HTTPError:
        return None, "Nao consegui falar com a API do Yuno."

    nickname_status = "Apelido nao alterado."
    if interaction.guild:
        try:
            member = await interaction.guild.fetch_member(int(record["requester_id"]))
            apelido = (record.get("payload") or {}).get("apelido_sugerido")
            if apelido:
                await member.edit(nick=apelido[:32], reason=f"Yuno set aprovado #{protocolo}")
                nickname_status = "Apelido atualizado."
        except discord.Forbidden:
            nickname_status = "Nao consegui alterar o apelido por falta de permissao."
        except discord.HTTPException:
            nickname_status = "Registro aprovado, mas nao consegui atualizar o apelido."

    await send_module_log(api, interaction, "set", approval_log_embed(interaction, record, nickname_status))
    return record, nickname_status


async def reject_set_record(api: YunoAPI, interaction: discord.Interaction, protocolo: int, motivo: str) -> tuple[dict | None, str]:
    try:
        record = await api.patch_record(
            module="set",
            record_id=protocolo,
            status="rejected",
            reviewer_id=interaction.user.id,
            payload={"motivo": motivo},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, "Solicitacao de set nao encontrada."
        return None, "Nao consegui reprovar este set agora."
    except httpx.HTTPError:
        return None, "Nao consegui falar com a API do Yuno."

    await send_module_log(api, interaction, "set", rejection_log_embed(interaction, record, motivo))
    return record, "Set reprovado."
