"""Logica pura de organizacao visual de canais/categorias."""

SEPARADOR_CANAIS = "┃"
ICONE_PASTA = "📁"
MAX_CHANNEL_NAME_LENGTH = 100


def eh_categoria_visual(name: str) -> bool:
    normalized_name = name.strip()
    return len(normalized_name) >= 3 and set(normalized_name) == {"▬"}


def nome_com_separador(nome: str) -> str | None:
    """Devolve o novo nome com o separador visual, ou None se ja tiver."""
    if SEPARADOR_CANAIS in nome:
        return None

    nome_limpo = nome.lstrip("-")
    numero = nome_limpo.split("-", 1)[0]
    if numero.isdigit():
        return f"{SEPARADOR_CANAIS}{ICONE_PASTA}-{nome_limpo}"[:MAX_CHANNEL_NAME_LENGTH]
    return f"{SEPARADOR_CANAIS}{nome}"[:MAX_CHANNEL_NAME_LENGTH]
