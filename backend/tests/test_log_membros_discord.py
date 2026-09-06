import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

import discord  # noqa: E402

from yuno_bot.domain_modules.log_membros import admin  # noqa: E402
from yuno_bot.domain_modules.log_membros import runtime  # noqa: E402
from yuno_bot.domain_modules.log_membros.domain import (  # noqa: E402
    AuditCandidate,
    JoinSnapshot,
    LeaveCause,
    LeaveSnapshot,
    detect_leave_cause,
    format_duration,
    is_new_account,
)
from yuno_bot.domain_modules.log_membros.embeds import (  # noqa: E402
    build_join_embed,
    build_leave_embed,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── domain.py: funções puras ────────────────────────────────────────────────


def test_is_new_account_threshold() -> None:
    assert is_new_account(NOW - timedelta(days=1), now=NOW) is True
    assert is_new_account(NOW - timedelta(days=6, hours=23), now=NOW) is True
    assert is_new_account(NOW - timedelta(days=7), now=NOW) is False
    assert is_new_account(NOW - timedelta(days=400), now=NOW) is False


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=0), "0 minutos"),
        (timedelta(minutes=1), "1 minuto"),
        (timedelta(minutes=45), "45 minutos"),
        (timedelta(hours=2, minutes=5), "2 horas, 5 minutos"),
        (timedelta(days=3, hours=1), "3 dias, 1 hora"),
        (timedelta(days=1), "1 dia"),
        (timedelta(days=400), "1 ano e 35 dias"),
        (timedelta(days=365), "1 ano"),
        (timedelta(days=800), "2 anos e 70 dias"),
    ],
)
def test_format_duration(delta: timedelta, expected: str) -> None:
    assert format_duration(delta) == expected


def test_format_duration_never_negative() -> None:
    assert format_duration(timedelta(seconds=-10)) == "0 minutos"


def test_detect_leave_cause_voluntary_when_no_recent_audit_entry() -> None:
    cause = detect_leave_cause([], member_id=10, left_at=NOW)
    assert cause == LeaveCause(kind="voluntary")


def test_detect_leave_cause_matches_kick_within_window() -> None:
    candidate = AuditCandidate(
        action="kick",
        target_id=10,
        moderator_id=999,
        created_at=NOW - timedelta(seconds=3),
        reason="Comportamento inadequado",
    )
    cause = detect_leave_cause([candidate], member_id=10, left_at=NOW)
    assert cause == LeaveCause(kind="kicked", moderator_id=999, reason="Comportamento inadequado")


def test_detect_leave_cause_matches_ban_within_window() -> None:
    candidate = AuditCandidate(
        action="ban", target_id=10, moderator_id=999, created_at=NOW - timedelta(seconds=9), reason=None
    )
    cause = detect_leave_cause([candidate], member_id=10, left_at=NOW)
    assert cause.kind == "banned"


def test_detect_leave_cause_ignores_entries_outside_window_or_other_targets() -> None:
    too_old = AuditCandidate(
        action="kick", target_id=10, moderator_id=999, created_at=NOW - timedelta(seconds=11), reason=None
    )
    other_target = AuditCandidate(
        action="kick", target_id=11, moderator_id=999, created_at=NOW - timedelta(seconds=1), reason=None
    )
    from_the_future = AuditCandidate(
        action="kick", target_id=10, moderator_id=999, created_at=NOW + timedelta(seconds=1), reason=None
    )
    cause = detect_leave_cause(
        [too_old, other_target, from_the_future], member_id=10, left_at=NOW
    )
    assert cause == LeaveCause(kind="voluntary")


def test_detect_leave_cause_picks_most_recent_match() -> None:
    older = AuditCandidate(
        action="kick", target_id=10, moderator_id=1, created_at=NOW - timedelta(seconds=8), reason=None
    )
    newer = AuditCandidate(
        action="ban", target_id=10, moderator_id=2, created_at=NOW - timedelta(seconds=2), reason="reincidencia"
    )
    cause = detect_leave_cause([older, newer], member_id=10, left_at=NOW)
    assert cause == LeaveCause(kind="banned", moderator_id=2, reason="reincidencia")


# ── embeds.py: montagem pura dos embeds ─────────────────────────────────────


def _join_snapshot(**overrides) -> JoinSnapshot:
    data = dict(
        member_id=10,
        member_mention="<@10>",
        display_name="Ana#0001",
        account_created_at=NOW - timedelta(days=30),
        joined_at=NOW,
        member_count=150,
    )
    data.update(overrides)
    return JoinSnapshot(**data)


def test_build_join_embed_highlights_new_accounts() -> None:
    snapshot = _join_snapshot(account_created_at=NOW - timedelta(days=1))
    embed = build_join_embed(snapshot, now=NOW)
    assert embed.title == "📥 Entrada de membro"
    assert "<@10>" in embed.description
    field_names = [field.name for field in embed.fields]
    assert "⚠️ Atenção" in field_names
    warning = next(field for field in embed.fields if field.name == "⚠️ Atenção")
    assert "CONTA NOVA" in warning.value
    assert "150" in [field.value for field in embed.fields if field.name == "Membros no servidor"][0]


def test_build_join_embed_omits_warning_for_established_accounts() -> None:
    snapshot = _join_snapshot(account_created_at=NOW - timedelta(days=365))
    embed = build_join_embed(snapshot, now=NOW)
    assert "⚠️ Atenção" not in [field.name for field in embed.fields]


def _leave_snapshot(**overrides) -> LeaveSnapshot:
    data = dict(
        member_id=10,
        display_name="Ana#0001",
        joined_at=NOW - timedelta(days=10),
        left_at=NOW,
        role_mentions=("<@&1>", "<@&2>"),
        cause=LeaveCause(kind="voluntary"),
        extra_message="",
    )
    data.update(overrides)
    return LeaveSnapshot(**data)


def test_build_leave_embed_voluntary() -> None:
    embed = build_leave_embed(_leave_snapshot())
    reason = next(field for field in embed.fields if field.name == "Motivo da saída")
    assert "conta própria" in reason.value
    roles = next(field for field in embed.fields if field.name == "Cargos")
    assert roles.value == "<@&1>, <@&2>"


def test_build_leave_embed_kicked_with_moderator_and_reason() -> None:
    snapshot = _leave_snapshot(
        cause=LeaveCause(kind="kicked", moderator_id=999, reason="spam"), role_mentions=()
    )
    embed = build_leave_embed(snapshot)
    reason = next(field for field in embed.fields if field.name == "Motivo da saída")
    assert "Expulso por <@999>" in reason.value
    assert "spam" in reason.value
    roles = next(field for field in embed.fields if field.name == "Cargos")
    assert roles.value == "Nenhum cargo."


def test_build_leave_embed_unknown_cause_when_audit_log_unavailable() -> None:
    embed = build_leave_embed(_leave_snapshot(cause=LeaveCause(kind="unknown")))
    reason = next(field for field in embed.fields if field.name == "Motivo da saída")
    assert "Motivo desconhecido" in reason.value


def test_build_leave_embed_includes_extra_message_when_configured() -> None:
    embed = build_leave_embed(_leave_snapshot(extra_message="Lembrete: revisar acessos."))
    observation = next(field for field in embed.fields if field.name == "Observação")
    assert observation.value == "Lembrete: revisar acessos."


def test_build_leave_embed_handles_missing_joined_at() -> None:
    embed = build_leave_embed(_leave_snapshot(joined_at=None))
    joined = next(field for field in embed.fields if field.name == "Entrou em")
    assert joined.value == "Desconhecido"
    assert "Tempo no servidor" not in [field.name for field in embed.fields]


# ── admin.py: linhas de resumo e preflight de publicação ────────────────────


def test_config_lines_render_undefined_placeholders() -> None:
    lines = admin._config_lines(dict(admin.EMPTY_CONFIG))
    assert "Ainda não definido" in lines
    assert "Nenhum (opcional)" in lines
    assert "Nenhuma (opcional)" in lines


class FakeRole:
    def __init__(self, role_id: int, *, position: int, default: bool = False) -> None:
        self.id = role_id
        self.position = position
        self._default = default
        self.mention = f"<@&{role_id}>"

    def is_default(self) -> bool:
        return self._default

    def __ge__(self, other) -> bool:
        return self.position >= getattr(other, "position", other)


def _guild_for_preflight(*, join_role: FakeRole | None = None, bot_can_manage_roles: bool = True):
    channel = MagicMock(spec=discord.TextChannel)
    channel.mention = "#log"
    channel.permissions_for.return_value = SimpleNamespace(view_channel=True, send_messages=True)
    bot_member = SimpleNamespace(
        top_role=FakeRole(500, position=500),
        guild_permissions=SimpleNamespace(manage_roles=bot_can_manage_roles),
    )
    roles = {join_role.id: join_role} if join_role else {}
    return SimpleNamespace(
        me=bot_member,
        get_channel=lambda channel_id: channel if channel_id in {100, 200} else None,
        get_role=lambda role_id: roles.get(role_id),
    )


def test_preflight_requires_both_channels() -> None:
    guild = _guild_for_preflight()
    errors = admin.preflight(guild, dict(admin.EMPTY_CONFIG))
    assert any("Canal de log de entrada" in error for error in errors)
    assert any("Canal de log de saída" in error for error in errors)


def test_preflight_rejects_same_channel_for_join_and_leave() -> None:
    guild = _guild_for_preflight()
    config = {**admin.EMPTY_CONFIG, "join_channel_id": "100", "leave_channel_id": "100"}
    errors = admin.preflight(guild, config)
    assert any("canais diferentes" in error for error in errors)


def test_preflight_accepts_valid_configuration_without_roles() -> None:
    guild = _guild_for_preflight()
    config = {**admin.EMPTY_CONFIG, "join_channel_id": "100", "leave_channel_id": "200"}
    assert admin.preflight(guild, config) == []


def test_preflight_rejects_role_above_bot_in_hierarchy() -> None:
    high_role = FakeRole(600, position=600)
    guild = _guild_for_preflight(join_role=high_role)
    config = {
        **admin.EMPTY_CONFIG,
        "join_channel_id": "100",
        "leave_channel_id": "200",
        "join_role_ids": ["600"],
    }
    errors = admin.preflight(guild, config)
    assert any("hierarquia" in error for error in errors)


def test_preflight_requires_manage_roles_permission_when_roles_configured() -> None:
    low_role = FakeRole(50, position=50)
    guild = _guild_for_preflight(join_role=low_role, bot_can_manage_roles=False)
    config = {
        **admin.EMPTY_CONFIG,
        "join_channel_id": "100",
        "leave_channel_id": "200",
        "join_role_ids": ["50"],
    }
    errors = admin.preflight(guild, config)
    assert any("Gerenciar Cargos" in error for error in errors)


# ── runtime.py: handlers de entrada/saída ───────────────────────────────────


class FakeAuditLogs:
    def __init__(self, entries: list) -> None:
        self._entries = entries

    def __aiter__(self):
        self._iterator = iter(self._entries)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeAPI:
    def __init__(self, *, lifecycle: str = "active", config: dict | None = None) -> None:
        self.lifecycle = lifecycle
        self.config = config or {}

    async def module_instance(self, guild_id: int, module_key: str) -> dict:
        assert module_key == "log_membros"
        return {"lifecycle": self.lifecycle}

    async def effective_configuration(self, guild_id: int, module_key: str) -> dict:
        assert module_key == "log_membros"
        return {"data": self.config}


def _fake_role(role_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=role_id, mention=f"<@&{role_id}>", is_default=lambda: False)


def _fake_member(
    *, member_id: int = 10, roles: tuple | None = None, joined_at: datetime | None = NOW
) -> SimpleNamespace:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    channel.send = AsyncMock()
    guild = SimpleNamespace(
        id=1,
        member_count=150,
        members=[],
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        get_channel=lambda channel_id: channel if channel_id == 100 else None,
        get_role=lambda role_id: _fake_role(role_id),
        audit_logs=lambda limit, action: FakeAuditLogs([]),
    )
    member = SimpleNamespace(
        id=member_id,
        guild=guild,
        mention=f"<@{member_id}>",
        created_at=NOW - timedelta(days=30),
        joined_at=joined_at,
        roles=list(roles or ()),
        add_roles=AsyncMock(),
    )
    guild.channel = channel
    return member


def test_handle_member_join_skips_when_module_not_active() -> None:
    async def run() -> None:
        member = _fake_member()
        api = FakeAPI(lifecycle="paused", config={"join_channel_id": "100"})
        bot = SimpleNamespace(log=MagicMock())
        await runtime.handle_member_join(bot, api, member)
        member.guild.channel.send.assert_not_called()

    asyncio.run(run())


def test_handle_member_join_assigns_roles_and_posts_embed() -> None:
    async def run() -> None:
        member = _fake_member()
        api = FakeAPI(config={"join_channel_id": "100", "join_role_ids": ["5", "6"]})
        bot = SimpleNamespace(log=MagicMock())
        await runtime.handle_member_join(bot, api, member)
        member.add_roles.assert_awaited_once()
        assigned = {role.id for role in member.add_roles.await_args.args}
        assert assigned == {5, 6}
        member.guild.channel.send.assert_awaited_once()
        embed = member.guild.channel.send.await_args.kwargs["embed"]
        assert embed.title == "📥 Entrada de membro"

    asyncio.run(run())


def test_handle_member_join_without_channel_still_assigns_roles() -> None:
    async def run() -> None:
        member = _fake_member()
        api = FakeAPI(config={"join_role_ids": ["5"]})
        bot = SimpleNamespace(log=MagicMock())
        await runtime.handle_member_join(bot, api, member)
        member.add_roles.assert_awaited_once()
        member.guild.channel.send.assert_not_called()

    asyncio.run(run())


def test_handle_member_remove_degrades_gracefully_without_audit_permission() -> None:
    async def run() -> None:
        member = _fake_member(roles=(_fake_role(1),))
        member.guild.me = SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=False))
        api = FakeAPI(config={"leave_channel_id": "100"})
        bot = SimpleNamespace(log=MagicMock())
        await runtime.handle_member_remove(bot, api, member)
        member.guild.channel.send.assert_awaited_once()
        embed = member.guild.channel.send.await_args.kwargs["embed"]
        reason_field = next(field for field in embed.fields if field.name == "Motivo da saída")
        assert "Motivo desconhecido" in reason_field.value

    asyncio.run(run())


def test_handle_member_remove_detects_kick_from_audit_log() -> None:
    async def run() -> None:
        member = _fake_member(roles=(_fake_role(1),))
        # `created_at` precisa ser recente em relação ao `datetime.now(timezone.utc)`
        # real que `handle_member_remove` vai calcular internamente — não dá para
        # congelar o relógio sem mexer no módulo, então ancoramos no agora real.
        entry = SimpleNamespace(
            target=SimpleNamespace(id=10),
            user=SimpleNamespace(id=999),
            created_at=datetime.now(timezone.utc) - timedelta(seconds=2),
            reason="baderna",
        )
        member.guild.audit_logs = lambda limit, action: (
            FakeAuditLogs([entry]) if action == discord.AuditLogAction.kick else FakeAuditLogs([])
        )
        api = FakeAPI(config={"leave_channel_id": "100"})
        bot = SimpleNamespace(log=MagicMock())
        await runtime.handle_member_remove(bot, api, member)

        embed = member.guild.channel.send.await_args.kwargs["embed"]
        reason_field = next(field for field in embed.fields if field.name == "Motivo da saída")
        assert "Expulso por <@999>" in reason_field.value
        assert "baderna" in reason_field.value

    asyncio.run(run())


def test_handle_member_remove_skips_when_leave_channel_missing() -> None:
    async def run() -> None:
        member = _fake_member()
        api = FakeAPI(config={})
        bot = SimpleNamespace(log=MagicMock())
        await runtime.handle_member_remove(bot, api, member)
        member.guild.channel.send.assert_not_called()

    asyncio.run(run())
