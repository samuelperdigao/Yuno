import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from app.domain_modules.registration.domain import (  # noqa: E402
    RegistrationDomainError,
    normalize_name,
    normalize_player_id,
    render_nickname,
    validate_nickname_template,
    validate_player_id,
)
from app.domain_modules.registration.schemas import RegistrationConfig  # noqa: E402
from yuno_bot.domain_modules.registration.ui import (  # noqa: E402
    render_public,
    render_review,
)


def test_registration_normalization_preserves_leading_zeroes_and_name_case() -> None:
    assert normalize_name("  JoAO\u00a0  da   Silva ") == "JoAO da Silva"
    assert normalize_player_id(" ００1AbC ") == "001abc"
    assert validate_player_id(
        " ００1 ", numeric_only=True, min_length=1, max_length=16
    ) == "001"
    with pytest.raises(RegistrationDomainError, match="ASCII"):
        validate_player_id("١٢٣", numeric_only=True, min_length=1, max_length=16)


def test_alphanumeric_player_id_accepts_only_ascii_letters_and_numbers() -> None:
    assert (
        validate_player_id(" AbC１２３ ", numeric_only=False, min_length=1, max_length=16)
        == "abc123"
    )
    for invalid in ("ABC-123", "ABC_123", "ABC 123", "ABC!", "ç123"):
        with pytest.raises(RegistrationDomainError, match="A a Z"):
            validate_player_id(invalid, numeric_only=False, min_length=1, max_length=16)


@pytest.mark.parametrize(
    "template",
    ("", "nickname fixo", "{unknown}", "{name.__class__}", "{name:>20}", "{{name}}"),
)
def test_registration_template_rejects_unknown_or_executable_syntax(template: str) -> None:
    with pytest.raises(RegistrationDomainError):
        validate_nickname_template(template)


def test_registration_template_renders_only_name_and_id_with_discord_limit() -> None:
    assert render_nickname("{name} | {id}", name="Ana", player_id="001") == "Ana | 001"
    assert validate_nickname_template("ID {id}") == "ID {id}"
    with pytest.raises(RegistrationDomainError, match="1 a 32"):
        render_nickname("{name} | {id}", name="A" * 32, player_id="001")


def test_registration_config_is_flat_strict_and_unbounded_by_role_select_batch() -> None:
    roles = [str(10_000 + value) for value in range(80)]
    config = RegistrationConfig(approver_role_ids=roles)
    assert config.enabled is True
    assert config.nickname_template == "{name} | {id}"
    assert config.player_id_numeric_only is True
    assert config.allow_resubmit_after_rejection is True
    assert config.approver_role_ids == roles
    assert config.log_approved_title == "Registro aprovado"
    assert config.log_rejected_title == "Registro rejeitado"
    assert config.log_footer == "Yuno • Sistema de Registro"
    assert config.show_member_avatar is True
    assert config.approved_dm_title == "Registro aprovado"
    assert config.rejected_dm_title == "Registro não aprovado"
    with pytest.raises(Exception):
        RegistrationConfig.model_validate({"unknown": True})


def test_registration_components_v2_public_and_decided_review_are_stable() -> None:
    config = RegistrationConfig().model_dump(mode="json")
    public = asyncio.run(render_public({"config": config})).data
    public_text = str(public)
    assert public["flags"] == 1 << 15
    assert public["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert "yuno:v1:registration:public:open_form" in public_text
    assert "Fazer meu registro" in public_text

    pending = asyncio.run(
        render_review(
            {
                "request": {
                    "discord_user_id": "10",
                    "submitted_name": "Ana",
                    "player_id_original": "001",
                    "status": "pending",
                    "reviewed_by": None,
                    "rejection_reason": None,
                    "created_at": "2026-08-22T12:00:00+00:00",
                },
                "avatar_url": "https://cdn.discordapp.com/avatar.png",
                "target_nickname": "Ana | 001",
            }
        )
    ).data
    decided = asyncio.run(
        render_review(
            {
                "request": {
                    "discord_user_id": "10",
                    "submitted_name": "Ana",
                    "player_id_original": "001",
                    "status": "approved",
                    "reviewed_by": "20",
                    "rejection_reason": None,
                    "created_at": "2026-08-22T12:00:00+00:00",
                    "approved_at": "2026-08-22T12:05:00+00:00",
                    "target_nickname": "Ana | 001",
                },
                "member_role_id": "30",
            }
        )
    ).data
    rejected = asyncio.run(
        render_review(
            {
                "request": {
                    "discord_user_id": "10",
                    "submitted_name": "Ana",
                    "player_id_original": "001",
                    "status": "rejected",
                    "reviewed_by": "20",
                    "rejection_reason": "Dados divergentes",
                    "created_at": "2026-08-22T12:00:00+00:00",
                    "rejected_at": "2026-08-22T12:06:00+00:00",
                }
            }
        )
    ).data
    assert "registration:review:approve" in str(pending)
    assert "registration:review:reject" in str(pending)
    assert "registration:review:approve" not in str(decided)
    assert "registration:review:reject" not in str(decided)
    assert pending["components"][0]["accent_color"] == 0xFFC72C
    assert decided["components"][0]["accent_color"] == 0x57F287
    assert pending["components"][0]["components"][0]["type"] == 9
    assert "Aguardando análise" in str(pending)
    assert "Apelido após aprovação" in str(pending)
    assert "approved" not in str(decided)
    assert rejected["components"][0]["accent_color"] == 0xED4245
    assert "registration:review:approve" not in str(rejected)
    assert "Dados divergentes" in str(rejected)
    assert "rejected" not in str(rejected)
