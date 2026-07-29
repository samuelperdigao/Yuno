"""Logica pura da escada de hierarquia -- sem discord.py, so IDs.

O MDM comparava por *nome* de cargo contra uma lista fixa (`HIERARQUIA_CARGOS`)
especifica do servidor dele. Aqui a escada e configuravel por servidor
(`settings.hierarquia.role_ids`, ordenada do menor para o maior cargo) e a
comparacao e por ID, que sobrevive a renomear o cargo -- nome nao.
"""


def cargo_atual(member_role_ids: list[int], ladder_role_ids: list[int]) -> int | None:
    """ID do cargo de hierarquia mais alto que o membro possui, ou None."""
    membro_ids = set(member_role_ids)
    melhor_idx = -1
    melhor_id: int | None = None
    for idx, role_id in enumerate(ladder_role_ids):
        if role_id in membro_ids and idx > melhor_idx:
            melhor_idx = idx
            melhor_id = role_id
    return melhor_id


def tipo_mudanca(ladder_role_ids: list[int], cargo_anterior_id: int | None, cargo_novo_id: int) -> str:
    if cargo_anterior_id is None:
        return "atribuicao"
    idx_anterior = ladder_role_ids.index(cargo_anterior_id) if cargo_anterior_id in ladder_role_ids else -1
    idx_novo = ladder_role_ids.index(cargo_novo_id) if cargo_novo_id in ladder_role_ids else -1
    if idx_novo > idx_anterior:
        return "promocao"
    if idx_novo < idx_anterior:
        return "rebaixamento"
    return "reatribuicao"
