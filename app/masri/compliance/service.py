"""Questionnaire + exemption persistence.

Thin layer over the SQLAlchemy models. Keeps the route handlers small
and keeps determinism rules (e.g. "re-submitting archives the previous
record") in one place.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app import db
from app.masri.compliance import engine, exemptions
from app.masri.new_models import ExemptionProfile, Questionnaire


def get_active_questionnaire(
    tenant_id: str, framework_slug: str
) -> Questionnaire | None:
    return (
        db.session.execute(
            db.select(Questionnaire)
            .filter(Questionnaire.tenant_id == tenant_id)
            .filter(Questionnaire.framework_slug == framework_slug)
            .filter(Questionnaire.status != "archived")
            .order_by(Questionnaire.date_added.desc())
        )
        .scalars()
        .first()
    )


def get_exemption_profile(
    tenant_id: str, framework_slug: str
) -> ExemptionProfile | None:
    return (
        db.session.execute(
            db.select(ExemptionProfile)
            .filter(ExemptionProfile.tenant_id == tenant_id)
            .filter(ExemptionProfile.framework_slug == framework_slug)
        )
        .scalars()
        .first()
    )


def save_draft(
    tenant_id: str,
    framework_slug: str,
    answers: dict[str, Any],
    *,
    user_id: str | None = None,
    project_id: str | None = None,
) -> Questionnaire:
    q = get_active_questionnaire(tenant_id, framework_slug)
    if q is None:
        q = Questionnaire(
            tenant_id=tenant_id,
            framework_slug=framework_slug,
            project_id=project_id,
            created_by_user_id=user_id,
            answers=answers,
            status="draft",
        )
        db.session.add(q)
    else:
        q.answers = answers
        q.status = "draft"
        if project_id and not q.project_id:
            q.project_id = project_id
    db.session.commit()
    return q


def submit(
    tenant_id: str,
    framework_slug: str,
    answers: dict[str, Any],
    *,
    user_id: str | None = None,
    project_id: str | None = None,
) -> tuple[Questionnaire, ExemptionProfile, list[str]]:
    """Submit the questionnaire: validate, persist, run exemption logic.

    Returns ``(questionnaire, exemption_profile, errors)``. When
    ``errors`` is non-empty, neither record is persisted.
    """
    bank = engine.get_bank(framework_slug)
    errors = engine.validate_answers(bank, answers)
    if errors:
        return None, None, errors  # type: ignore[return-value]

    q = save_draft(
        tenant_id, framework_slug, answers, user_id=user_id, project_id=project_id
    )
    q.status = "complete"
    q.completed_at = datetime.utcnow()

    determination = exemptions.determine(framework_slug, answers)

    profile = get_exemption_profile(tenant_id, framework_slug)
    if profile is None:
        profile = ExemptionProfile(
            tenant_id=tenant_id,
            framework_slug=framework_slug,
            questionnaire_id=q.id,
            **determination,
            determined_at=datetime.utcnow(),
        )
        db.session.add(profile)
    else:
        profile.questionnaire_id = q.id
        profile.exemption_type = determination["exemption_type"]
        profile.exemptions_claimed = determination["exemptions_claimed"]
        profile.scope_waived = determination["scope_waived"]
        profile.rationale = determination["rationale"]
        profile.determined_at = datetime.utcnow()
    db.session.commit()
    return q, profile, []


def mark_exemption_filed(
    tenant_id: str, framework_slug: str, confirmation: str | None = None
) -> ExemptionProfile | None:
    profile = get_exemption_profile(tenant_id, framework_slug)
    if not profile:
        return None
    profile.filed_at = datetime.utcnow()
    if confirmation:
        profile.filing_confirmation = confirmation
    db.session.commit()
    return profile
