import mimetypes
import re
import unicodedata
from datetime import datetime

import discord

from yuno_bot.commands.shared import YUNO_GREEN, clean_text, make_log_embed


PARCERIA_GOLD = discord.Color.from_rgb(255, 215, 0)
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def build_parceria_payload(nome: str, produto_servico: str, contato_principal: str, contato_secundario: str, observacao: str) -> dict[str, str]:
    return {
        "nome": nome.strip(),
        "produto_servico": produto_servico.strip(),
        "contato_principal": clean_text(contato_principal),
        "contato_secundario": clean_text(contato_secundario),
        "observacao": clean_text(observacao),
    }


def parceria_post_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Parceria cadastrada", color=YUNO_GREEN, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="Produto/servico", value=payload["produto_servico"], inline=False)
    embed.add_field(name="Contato principal", value=payload["contato_principal"], inline=True)
    embed.add_field(name="Contato secundario", value=payload["contato_secundario"], inline=True)
    embed.add_field(name="Observacao", value=payload["observacao"][:1024], inline=False)
    embed.set_footer(text=f"Cadastrada por {interaction.user.display_name}")
    return embed


def parceria_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Parceria cadastrada", interaction, color=YUNO_GREEN)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="Produto/servico", value=payload["produto_servico"], inline=False)
    return embed


def parcerias_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Painel de Parcerias",
        description="\n".join(
            [
                "Use os botões abaixo para registrar, editar ou remover parcerias ativas.",
                "As imagens dos uniformes ficam salvas diretamente na lista pública.",
            ]
        ),
        color=PARCERIA_GOLD,
    )
    embed.add_field(name="Registro", value="Crie uma nova parceria com produto, contatos e uniforme.", inline=False)
    embed.add_field(name="Lista ativa", value="Cada família ativa aparece em uma única mensagem atualizada.", inline=False)
    embed.set_footer(text="Sistema de Parcerias")
    return embed


def parceria_active_embed(
    parceria: dict,
    *,
    attachment_filename: str | None = None,
    image_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=parceria["nome_familia"], color=PARCERIA_GOLD)
    embed.add_field(name="🛒 Produto", value=parceria["produto"], inline=False)
    if parceria.get("contato_01"):
        embed.add_field(name="📞 Contato Principal", value=parceria["contato_01"], inline=False)
    if parceria.get("contato_02"):
        embed.add_field(name="📞 Contato Secundário", value=parceria["contato_02"], inline=False)
    if attachment_filename:
        embed.set_image(url=f"attachment://{attachment_filename}")
    elif image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Parceria registrada em {format_brazilian_date(parceria.get('criado_em'))}")
    return embed


def format_brazilian_date(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                parsed = datetime.strptime(value.strip().split(".")[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return value.strip()
    else:
        parsed = discord.utils.utcnow()
    return parsed.strftime("%d/%m/%Y às %H:%M")


def image_extension(filename: str | None, content_type: str | None = None) -> str | None:
    if filename:
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix in ALLOWED_IMAGE_EXTENSIONS:
            return suffix
    if content_type and content_type.lower().startswith("image/"):
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower())
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed in ALLOWED_IMAGE_EXTENSIONS:
            return guessed
    return None


def is_valid_image_attachment(filename: str | None, content_type: str | None = None) -> bool:
    if filename:
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix in ALLOWED_IMAGE_EXTENSIONS:
            return True
    return bool(content_type and content_type.lower().startswith("image/"))


def uniform_filename(nome_familia: str, original_filename: str | None, content_type: str | None = None) -> str:
    extension = image_extension(original_filename, content_type) or ".png"
    return f"uniforme_{slugify_family_name(nome_familia)}{extension}"


def slugify_family_name(nome_familia: str) -> str:
    normalized = unicodedata.normalize("NFKD", nome_familia)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "familia"
