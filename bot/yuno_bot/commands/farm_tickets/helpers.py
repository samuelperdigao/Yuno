from datetime import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord


SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class MemberFolderError(ValueError):
    pass


@dataclass(frozen=True)
class MemberFolderIdentity:
    channel_id: int
    slot: int
    nickname: str
    game_id: str


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


def build_ticket_channel_name(member: discord.Member, member_name: str | None = None) -> str:
    return f"farm-{sanitize_channel_part(member_name or member.display_name)}-{member.id}"


def build_ticket_channel_name_from_folder(member: discord.Member, folder: MemberFolderIdentity | None) -> str:
    if not folder:
        return build_ticket_channel_name(member)
    return f"farm-{folder.slot:02d}-{sanitize_channel_part(folder.nickname)}-{folder.game_id}"


def _folder_normalized_name(channel_name: str) -> str:
    return channel_name.replace("┃", "").replace("📁", "").strip().lstrip("-")


def parse_member_folder(channel_name: str, channel_id: int) -> MemberFolderIdentity:
    parts = _folder_normalized_name(channel_name).split("-")
    if len(parts) < 3 or not parts[0].isdigit() or not parts[-1].isdigit():
        raise MemberFolderError("A pasta nao possui slot, apelido e ID do jogo validos.")
    nickname_parts = [part for part in parts[1:-1] if part]
    if not nickname_parts:
        raise MemberFolderError("A pasta nao possui um apelido valido.")
    return MemberFolderIdentity(
        channel_id=channel_id,
        slot=int(parts[0]),
        nickname=" ".join(nickname_parts).title(),
        game_id=parts[-1],
    )


def next_folder_slot(category: discord.CategoryChannel) -> int:
    slots: list[int] = []
    for channel in category.text_channels:
        try:
            slots.append(parse_member_folder(channel.name, channel.id).slot)
        except MemberFolderError:
            continue
    current = 1
    used = set(slots)
    while current in used:
        current += 1
    return current


def member_folder_nickname_and_game_id(member: discord.Member) -> tuple[str, str]:
    display_name = member.display_name.strip()
    if "|" in display_name:
        nickname, possible_game_id = [part.strip() for part in display_name.rsplit("|", 1)]
        if nickname and possible_game_id.isdigit():
            return nickname, possible_game_id
    return display_name or member.name, str(member.id)


def _has_explicit_member_access(channel: discord.TextChannel, member: discord.Member) -> bool:
    for target, overwrite in channel.overwrites.items():
        if getattr(target, "id", None) == member.id and overwrite.view_channel is True:
            return True
    return False


async def resolve_member_folder(
    guild: discord.Guild,
    member: discord.Member,
    category_id: int | None,
    admin_role_ids: list[str] | None = None,
) -> MemberFolderIdentity | None:
    if not category_id:
        return None
    category = guild.get_channel(category_id)
    if category is None:
        try:
            category = await guild.fetch_channel(category_id)
        except discord.HTTPException as exc:
            raise MemberFolderError("A categoria de pastas privadas nao esta disponivel.") from exc
    if not isinstance(category, discord.CategoryChannel):
        raise MemberFolderError("A categoria de pastas privadas nao esta disponivel.")

    candidates = [
        channel
        for channel in category.text_channels
        if "livre" not in channel.name.casefold() and _has_explicit_member_access(channel, member)
    ]
    if not candidates and member.guild_permissions.administrator:
        admin_folders: list[MemberFolderIdentity] = []
        for channel in category.text_channels:
            if "livre" in channel.name.casefold():
                continue
            try:
                identity = parse_member_folder(channel.name, channel.id)
            except MemberFolderError:
                continue
            if identity.slot == 0:
                admin_folders.append(identity)
        if len(admin_folders) == 1:
            return admin_folders[0]
        if len(admin_folders) > 1:
            raise MemberFolderError("Mais de uma pasta administrativa de slot 0 foi encontrada.")
    if not candidates:
        raise MemberFolderError("Nenhuma pasta individual valida foi encontrada para voce.")
    if len(candidates) > 1:
        raise MemberFolderError("Mais de uma pasta esta vinculada ao membro; procure a administracao.")
    return parse_member_folder(candidates[0].name, candidates[0].id)


async def resolve_or_create_member_folder(
    guild: discord.Guild,
    member: discord.Member,
    category_id: int | None,
    admin_role_ids: list[str] | None = None,
) -> MemberFolderIdentity:
    try:
        folder = await resolve_member_folder(guild, member, category_id, admin_role_ids)
        if folder:
            return folder
    except MemberFolderError as exc:
        if "Nenhuma pasta individual valida" not in str(exc):
            raise

    category = guild.get_channel(int(category_id)) if category_id else None
    if category is None and category_id:
        try:
            category = await guild.fetch_channel(int(category_id))
        except discord.HTTPException as exc:
            raise MemberFolderError("A categoria de pastas privadas nao esta disponivel.") from exc
    if not isinstance(category, discord.CategoryChannel):
        raise MemberFolderError("A categoria de pastas privadas nao esta disponivel.")

    slot = next_folder_slot(category)
    nickname, game_id = member_folder_nickname_and_game_id(member)
    channel_name = f"┃📁-{slot}-{sanitize_channel_part(nickname)}-{game_id}"
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
    }
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    for role_id in admin_role_ids or []:
        try:
            role = guild.get_role(int(role_id))
        except (TypeError, ValueError):
            role = None
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
            )
    channel = await guild.create_text_channel(
        channel_name,
        category=category,
        overwrites=overwrites,
        reason="Criacao automatica de pasta individual para farm",
    )
    return MemberFolderIdentity(channel_id=channel.id, slot=slot, nickname=nickname, game_id=game_id)


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
