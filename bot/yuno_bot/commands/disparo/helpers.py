"""Selecao de canais-alvo do disparo.

O MDM tinha uma categoria hardcoded (`BROADCAST_CATEGORY_ID`), uma regex
propria pra reconhecer pasta de membro e uma lista de nomes de canal
bloqueados (tutoriais, avisos, fichas...) escrita a mao. No Yuno a
categoria ja e configuravel (`settings.farm_tickets.folders_category_id`)
e o reconhecimento de pasta reaproveita `parse_member_folder`, que ja e a
fonte da verdade para "isso e uma pasta de membro" -- qualquer canal que
nao seguir o padrao (tutorial, aviso, divisor visual) simplesmente falha
o parse e fica de fora, sem precisar de lista de bloqueio nenhuma.
"""

import discord

from yuno_bot.commands.farm_tickets.helpers import MemberFolderError, parse_member_folder


def valid_member_channels(category: discord.CategoryChannel) -> list[discord.TextChannel]:
    validos = []
    for channel in category.text_channels:
        if "livre" in channel.name.casefold():
            continue
        try:
            parse_member_folder(channel.name, channel.id)
        except MemberFolderError:
            continue
        validos.append(channel)
    return validos
