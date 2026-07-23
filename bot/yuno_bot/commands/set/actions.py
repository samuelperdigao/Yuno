import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.set.embeds import approval_log_embed, rejection_log_embed
from yuno_bot.commands.shared import get_guild_config, send_module_log


async def approve_set_record(api: YunoAPI, interaction: discord.Interaction, protocolo: int) -> tuple[dict | None, str]:
    try:
        record = await api.patch_record(module="set", record_id=protocolo, status="approved", reviewer_id=interaction.user.id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, "Solicitacao de set nao encontrada."
        return None, "Nao consegui aprovar este set agora."
    except httpx.HTTPError:
        return None, "Nao consegui falar com a API do Yuno."

    status_messages: list[str] = []
    if interaction.guild:
        member = None
        try:
            member = await interaction.guild.fetch_member(int(record["requester_id"]))
        except discord.HTTPException:
            status_messages.append("Nao consegui encontrar o membro no servidor.")

        if member:
            apelido = (record.get("payload") or {}).get("apelido_sugerido")
            if apelido:
                try:
                    await member.edit(nick=apelido[:32], reason=f"Yuno set aprovado #{protocolo}")
                    status_messages.append("Apelido atualizado.")
                except discord.Forbidden:
                    status_messages.append("Nao consegui alterar o apelido por falta de permissao.")
                except discord.HTTPException:
                    status_messages.append("Registro aprovado, mas nao consegui atualizar o apelido.")
            else:
                status_messages.append("Apelido nao informado no registro.")

            role_status = await _add_approved_role(api, interaction, member, protocolo)
            status_messages.append(role_status)
    else:
        status_messages.append("Registro aprovado fora de um servidor Discord.")

    status_message = " ".join(status_messages)
    await send_module_log(api, interaction, "set", approval_log_embed(interaction, record, status_message))
    return record, status_message


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


async def _add_approved_role(api: YunoAPI, interaction: discord.Interaction, member: discord.Member, protocolo: int) -> str:
    if not interaction.guild:
        return "Cargo aprovado nao aplicado fora de um servidor."

    config = await get_guild_config(api, interaction.guild.id)
    role_id = ((config.get("settings") or {}).get("set") or {}).get("approved_role_id")
    if not role_id:
        return "Cargo aprovado nao configurado."

    try:
        role_id_int = int(role_id)
    except (TypeError, ValueError):
        return "Cargo aprovado configurado com ID invalido."

    role = interaction.guild.get_role(role_id_int)
    if not role:
        return "Cargo aprovado nao encontrado no servidor."

    try:
        await member.add_roles(role, reason=f"Yuno set aprovado #{protocolo}")
    except discord.Forbidden:
        return "Nao consegui adicionar o cargo por falta de permissao."
    except discord.HTTPException:
        return "Registro aprovado, mas nao consegui adicionar o cargo."
    return f"Cargo {role.mention} aplicado."
