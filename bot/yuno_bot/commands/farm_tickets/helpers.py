from datetime import datetime
from zoneinfo import ZoneInfo

import discord


SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def current_week_id(now: datetime | None = None) -> str:
    local_now = now.astimezone(SAO_PAULO_TZ) if now else datetime.now(SAO_PAULO_TZ)
    year, week, _ = local_now.isocalendar()
    return f"{year}-W{week:02d}"


def parse_discord_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        digits = "".join(char for char in part if char.isdigit())
        if digits:
            parsed = int(digits)
            if parsed not in ids:
                ids.append(parsed)
    return ids


def sanitize_channel_part(value: str) -> str:
    normalized = value.lower().strip()
    cleaned = []
    for char in normalized:
        if char.isalnum():
            cleaned.append(char)
        elif char in {" ", "-", "_", "."}:
            cleaned.append("-")
    text = "".join(cleaned).strip("-")
    while "--" in text:
        text = text.replace("--", "-")
    return text[:40] or "membro"


def build_ticket_channel_name(member: discord.Member) -> str:
    return f"farm-{sanitize_channel_part(member.display_name)}-{member.id}"


def choose_ticket_category(guild: discord.Guild, category_ids: list[str]) -> discord.CategoryChannel | None:
    for category_id in category_ids:
        category = guild.get_channel(int(category_id))
        if isinstance(category, discord.CategoryChannel) and len(category.channels) < 50:
            return category
    return None


def is_valid_image_message(message: discord.Message) -> bool:
    for attachment in message.attachments:
        content_type = attachment.content_type or ""
        if content_type.startswith("image/") or attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
            return True
    return False


def first_image_url(message: discord.Message) -> str | None:
    for attachment in message.attachments:
        content_type = attachment.content_type or ""
        if content_type.startswith("image/") or attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
            return attachment.url
    return None


def member_has_any_role(member: discord.Member, role_ids: list[str]) -> bool:
    if not role_ids:
        return True
    member_roles = {str(role.id) for role in member.roles}
    return bool(member_roles.intersection(set(role_ids)))


def is_farm_admin(member: discord.Member, config: dict) -> bool:
    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True
    role_ids = set(config.get("admin_role_ids") or [])
    return bool({str(role.id) for role in member.roles}.intersection(role_ids))
