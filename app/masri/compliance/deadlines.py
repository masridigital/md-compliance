"""Compliance deadline seeding + listing.

Reuses :class:`app.masri.new_models.DueDate` (entity_type ``"compliance_deadline"``)
so existing reminder machinery (NotificationEngine.check_and_send_due_reminders
and the daily Celery beat ``task_due_reminders``) picks up new items for
free — no schema change needed.

The ``entity_id`` carries a structured identifier:
``<framework_slug>::<deadline_kind>::<tenant_id>`` so duplicates can be
detected on re-seed.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Any

from app import db
from app.masri.compliance import framework_meta
from app.masri.compliance.service import get_exemption_profile
from app.masri.new_models import DueDate

logger = logging.getLogger(__name__)


ENTITY_TYPE = "compliance_deadline"


def _entity_id(framework_slug: str, kind: str, tenant_id: str) -> str:
    return f"{framework_slug}::{kind}::{tenant_id}"


def _next_annual_due(due_month_day: str | None) -> datetime:
    """Return the next future occurrence of a month-day pair (MM-DD)."""
    today = date.today()
    if not due_month_day:
        # No fixed date — default to 60 days from today
        return datetime.combine(today + timedelta(days=60), datetime.min.time())
    try:
        month_str, day_str = due_month_day.split("-")
        month = int(month_str)
        day = int(day_str)
    except (ValueError, AttributeError):
        return datetime.combine(today + timedelta(days=60), datetime.min.time())

    year = today.year
    candidate = _safe_date(year, month, day)
    if candidate < today:
        candidate = _safe_date(year + 1, month, day)
    return datetime.combine(candidate, datetime.min.time())


def _safe_date(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _recurrence_in_days(recurrence: str | None) -> int | None:
    return {"annual": 365, "biennial": 730}.get(recurrence or "")


def _deadline_applies(
    deadline: dict[str, Any],
    exempt_codes: set[str],
    is_exempt: bool,
) -> bool:
    """Apply ``only_if_exempt`` / ``only_if_not_exempt`` gating."""
    if deadline.get("only_if_exempt") and not is_exempt:
        return False
    block = set(deadline.get("only_if_not_exempt") or [])
    if block and exempt_codes.intersection(block):
        return False
    return True


def seed_deadlines_for_tenant(tenant_id: str, framework_slug: str) -> int:
    """Create/refresh DueDate rows for a (tenant, framework) pair.

    Returns the number of deadline rows created or updated.
    """
    meta = framework_meta.load(framework_slug) or {}
    definitions = meta.get("deadlines") or []
    if not definitions:
        return 0

    profile = get_exemption_profile(tenant_id, framework_slug)
    exempt_codes: set[str] = set()
    if profile and profile.exemptions_claimed:
        exempt_codes = {
            code for code, on in (profile.exemptions_claimed or {}).items() if on
        }
    is_exempt = bool(profile and profile.exemption_type != "none")

    created_or_updated = 0
    for definition in definitions:
        if not _deadline_applies(definition, exempt_codes, is_exempt):
            _retire_deadline(tenant_id, framework_slug, definition["kind"])
            continue

        kind = definition["kind"]
        entity_id = _entity_id(framework_slug, kind, tenant_id)
        due_at = _next_annual_due(definition.get("due_month_day"))

        existing = (
            db.session.execute(
                db.select(DueDate)
                .filter(DueDate.tenant_id == tenant_id)
                .filter(DueDate.entity_type == ENTITY_TYPE)
                .filter(DueDate.entity_id == entity_id)
            )
            .scalars()
            .first()
        )
        if existing is None:
            row = DueDate(
                tenant_id=tenant_id,
                entity_type=ENTITY_TYPE,
                entity_id=entity_id,
                due_date=due_at,
                status="pending",
            )
            db.session.add(row)
            created_or_updated += 1
        elif existing.status == "pending" and existing.due_date != due_at:
            # Keep future scheduling in sync with questionnaire-driven changes.
            existing.due_date = due_at
            created_or_updated += 1

    db.session.commit()
    logger.info(
        "Seeded %d compliance deadlines for tenant=%s framework=%s",
        created_or_updated,
        tenant_id,
        framework_slug,
    )
    return created_or_updated


def _retire_deadline(tenant_id: str, framework_slug: str, kind: str) -> None:
    """Dismiss a deadline that the exemption profile makes inapplicable."""
    entity_id = _entity_id(framework_slug, kind, tenant_id)
    existing = (
        db.session.execute(
            db.select(DueDate)
            .filter(DueDate.tenant_id == tenant_id)
            .filter(DueDate.entity_type == ENTITY_TYPE)
            .filter(DueDate.entity_id == entity_id)
            .filter(DueDate.status == "pending")
        )
        .scalars()
        .first()
    )
    if existing:
        existing.status = "dismissed"


def list_deadlines(
    tenant_id: str,
    *,
    framework_slug: str | None = None,
    include_completed: bool = False,
) -> list[dict[str, Any]]:
    """Return human-friendly deadline dicts for the UI."""
    stmt = (
        db.select(DueDate)
        .filter(DueDate.tenant_id == tenant_id)
        .filter(DueDate.entity_type == ENTITY_TYPE)
        .order_by(DueDate.due_date.asc())
    )
    if not include_completed:
        stmt = stmt.filter(DueDate.status.in_(["pending", "overdue"]))
    rows = db.session.execute(stmt).scalars().all()

    frameworks_seen: set[str] = set()
    metas: dict[str, dict[str, Any]] = {}

    def _meta(slug: str) -> dict[str, Any]:
        if slug not in metas:
            metas[slug] = framework_meta.load(slug) or {}
        return metas[slug]

    out: list[dict[str, Any]] = []
    for row in rows:
        parts = (row.entity_id or "").split("::")
        if len(parts) < 2:
            continue
        slug, kind = parts[0], parts[1]
        if framework_slug and slug != framework_slug:
            continue
        frameworks_seen.add(slug)
        m = _meta(slug)
        label = kind
        recurrence = None
        for d in m.get("deadlines", []):
            if d["kind"] == kind:
                label = d["label"]
                recurrence = d.get("recurrence")
                break
        data = row.as_dict()
        data.update({
            "framework_slug": slug,
            "kind": kind,
            "label": label,
            "recurrence": recurrence,
        })
        out.append(data)
    return out
