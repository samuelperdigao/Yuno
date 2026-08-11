import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError


os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.main import app  # noqa: E402
from app.db import Base  # noqa: E402
from app.domain_modules.farm.definition import FARM_CONFIGURATION, MODULE_DEFINITION  # noqa: E402
from app.domain_modules.farm.domain import (  # noqa: E402
    CYCLE_TRANSITIONS,
    SUBMISSION_TRANSITIONS,
    CycleStatus,
    FarmDomainError,
    SubmissionStatus,
    calculate_progress,
    ensure_transition,
    normalize_name,
    normalize_quantity,
)
from app.domain_modules.farm.schemas import (  # noqa: E402
    CycleCreate,
    ReviewCreate,
    SubmissionCreate,
    TemplateCreate,
)


def test_farm_definition_is_domain_first_and_composable() -> None:
    assert MODULE_DEFINITION.manifest.key == "farm"
    assert MODULE_DEFINITION.manifest.default_runtime_mode == "legacy"
    assert MODULE_DEFINITION.manifest.runtime_modes == ("legacy", "shadow", "domain")
    assert MODULE_DEFINITION.lifecycle.requires_published_configuration is True
    assert MODULE_DEFINITION.capability("farm.submit_own").allow_resource_owner is True
    assert MODULE_DEFINITION.capability("farm.close_cycle").allow_automation is True
    assert MODULE_DEFINITION.panel("ticket").instance_type == "resource"
    assert MODULE_DEFINITION.job("farm.cycle.finish_closing").max_attempts == 10
    assert MODULE_DEFINITION.migration.key == "farm-v2"
    assert {item.key for item in MODULE_DEFINITION.health_checks} == {"farm-domain"}


def test_farm_configuration_has_only_runtime_and_discord_settings() -> None:
    valid = {
        **FARM_CONFIGURATION.defaults(),
        "ticket_category_ids": ["category-a", "category-b"],
        "public_panel_channel_id": "public",
        "review_panel_channel_id": "review",
    }
    assert FARM_CONFIGURATION.validate(valid) == []
    assert FARM_CONFIGURATION.validate({**valid, "products": []}) == ["Campo desconhecido: products."]
    assert "Categoria de tickets duplicada." in FARM_CONFIGURATION.validate(
        {**valid, "ticket_category_ids": ["same", "same"]}
    )


def test_farm_relational_tables_are_registered_without_replacing_legacy() -> None:
    expected = {
        "farm_products",
        "farm_templates",
        "farm_template_items",
        "farm_cycles",
        "farm_cycle_goals",
        "farm_cycle_participants",
        "farm_cycle_tickets",
        "farm_submissions",
        "farm_submission_items",
        "farm_proofs",
        "farm_reviews",
    }
    assert expected.issubset(Base.metadata.tables)
    assert "farm_tickets" in Base.metadata.tables
    assert Base.metadata.tables["farm_cycle_tickets"] is not Base.metadata.tables["farm_tickets"]


def test_names_quantities_and_progress_are_domain_rules() -> None:
    assert normalize_name("  Kit   MÉDICO ") == "kit médico"
    assert normalize_quantity("10.25", 2) == Decimal("10.25")
    with pytest.raises(FarmDomainError, match="precisao"):
        normalize_quantity("10.251", 2)
    with pytest.raises(FarmDomainError, match="positiva"):
        normalize_quantity("0", 0)

    progress = calculate_progress(
        {1: Decimal("10"), 2: Decimal("20")},
        [(1, Decimal("12")), (2, Decimal("5")), (999, Decimal("100"))],
    )
    assert progress.items[1].approved == Decimal("12")
    assert progress.items[1].percent == Decimal("120.00")
    assert progress.percent == Decimal("62.50")
    assert progress.completed is False


def test_state_machines_reject_shortcuts_and_allow_claim_release() -> None:
    ensure_transition(CycleStatus.draft, CycleStatus.scheduled, CYCLE_TRANSITIONS)
    with pytest.raises(FarmDomainError, match="nao permitida"):
        ensure_transition(CycleStatus.draft, CycleStatus.closed, CYCLE_TRANSITIONS)
    ensure_transition(SubmissionStatus.submitted, SubmissionStatus.under_review, SUBMISSION_TRANSITIONS)
    ensure_transition(SubmissionStatus.under_review, SubmissionStatus.submitted, SUBMISSION_TRANSITIONS)
    with pytest.raises(FarmDomainError):
        ensure_transition(SubmissionStatus.approved, SubmissionStatus.rejected, SUBMISSION_TRANSITIONS)


def test_schemas_reject_duplicate_products_invalid_dates_and_unjustified_review() -> None:
    with pytest.raises(ValidationError, match="Produto duplicado"):
        TemplateCreate(
            name="Semanal",
            items=[
                {"product_id": 1, "quantity": "10"},
                {"product_id": 1, "quantity": "20"},
            ],
        )

    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="posterior"):
        CycleCreate(
            template_id=1,
            title="Ciclo",
            timezone="America/Sao_Paulo",
            starts_at=now,
            ends_at=now - timedelta(minutes=1),
        )
    with pytest.raises(ValidationError, match="timezone"):
        CycleCreate(
            template_id=1,
            title="Ciclo",
            timezone="America/Sao_Paulo",
            starts_at=now.replace(tzinfo=None),
            ends_at=(now + timedelta(hours=1)).replace(tzinfo=None),
        )

    with pytest.raises(ValidationError, match="Justificativa"):
        ReviewCreate(
            reviewer_id="reviewer",
            decision="rejected",
            idempotency_key="review-1",
        )


def test_submission_requires_proof_and_unique_goal_items() -> None:
    base = {
        "submitted_by": "member",
        "items": [{"goal_id": 1, "quantity": "5"}],
        "proofs": [{"channel_id": "c", "message_id": "m", "url": "https://example.invalid/proof"}],
        "idempotency_key": "submission-1",
    }
    assert SubmissionCreate(**base).proofs
    with pytest.raises(ValidationError):
        SubmissionCreate(**{**base, "proofs": []})
    with pytest.raises(ValidationError, match="HTTP"):
        SubmissionCreate(**{**base, "proofs": [{"channel_id": "c", "message_id": "m", "url": "javascript:bad"}]})
    with pytest.raises(ValidationError, match="Meta duplicada"):
        SubmissionCreate(
            **{
                **base,
                "items": [
                    {"goal_id": 1, "quantity": "5"},
                    {"goal_id": 1, "quantity": "6"},
                ],
            }
        )


def test_farm_migration_is_additive_and_chained_to_platform_foundation() -> None:
    source = (
        ROOT / "backend" / "migrations" / "versions" / "f2a1b3c4d5e6_add_farm_domain.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"' in source
    assert '"farm_cycle_tickets"' in source
    assert '"farm_tickets"' not in source
    assert "ALTER TABLE farm_tickets" not in source


def test_farm_api_exposes_the_complete_internal_vertical() -> None:
    operations = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if "/modules/farm/" in getattr(route, "path", "")
    }
    assert len(operations) == 23
    assert ("POST", "/internal/platform/guilds/{guild_id}/modules/farm/inventory") in operations
    assert ("POST", "/internal/platform/guilds/{guild_id}/modules/farm/templates/{template_id}/versions") in operations
    assert ("POST", "/internal/platform/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/participants") in operations
    assert ("POST", "/internal/platform/guilds/{guild_id}/modules/farm/tickets/{ticket_id}/submissions") in operations
    assert ("POST", "/internal/platform/guilds/{guild_id}/modules/farm/submissions/{submission_id}/review") in operations
