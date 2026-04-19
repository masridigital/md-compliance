"""
Notification service — channels + due-date reminders.

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.

Due-dates live alongside notification channels because the reminder
pipeline in :mod:`app.masri.notification_engine` reads both together —
overdue flagging is part of the same workflow that schedules channel
deliveries.
"""

from datetime import datetime, timedelta
from typing import Any, List, Mapping, Optional

from app import db
from app.masri.new_models import DueDate, SettingsNotifications


_BOOL_FIELDS = frozenset({
    "enabled",
    "critical_enabled",
    "high_enabled",
    "medium_enabled",
    "low_enabled",
})


def get_notification_channels(
    tenant_id: Optional[str] = None,
) -> List[SettingsNotifications]:
    """Return notification channel rows.

    If ``tenant_id`` is given, include both tenant-scoped and
    platform-default (``tenant_id IS NULL``) rows — the tenant inherits
    the platform defaults when no override exists.
    """
    stmt = db.select(SettingsNotifications)
    if tenant_id:
        stmt = stmt.filter(
            (SettingsNotifications.tenant_id == tenant_id)
            | (SettingsNotifications.tenant_id.is_(None))
        )
    return list(db.session.execute(stmt).scalars().all())


def update_notification_channel(
    channel: str,
    data: Mapping[str, Any],
    tenant_id: Optional[str] = None,
) -> SettingsNotifications:
    """Create or update a channel row for ``(channel, tenant_id)`` and commit.

    ``data`` may carry bool fields (see ``_BOOL_FIELDS``) and a nested
    ``config`` dict that is persisted via
    :meth:`SettingsNotifications.save_config`.
    """
    record = db.session.execute(
        db.select(SettingsNotifications).filter_by(
            channel=channel, tenant_id=tenant_id
        )
    ).scalars().first()
    if record is None:
        record = SettingsNotifications(channel=channel, tenant_id=tenant_id)
        db.session.add(record)

    for key, value in data.items():
        if key in _BOOL_FIELDS:
            setattr(record, key, value)

    if "config" in data and isinstance(data["config"], dict):
        record.save_config(data["config"])

    db.session.commit()
    return record


# ---------------------------------------------------------------------------
# Due dates
# ---------------------------------------------------------------------------

def get_due_dates(
    tenant_id: str,
    status: Optional[str] = None,
    days_ahead: Optional[int] = None,
) -> List[DueDate]:
    """Return ``DueDate`` rows for ``tenant_id`` ordered by ``due_date`` ASC.

    Optional filters:
      * ``status`` — exact match (``pending`` / ``completed`` / ``overdue`` / ``dismissed``)
      * ``days_ahead`` — only rows due within N days from now.
    """
    stmt = db.select(DueDate).filter_by(tenant_id=tenant_id)
    if status:
        stmt = stmt.filter_by(status=status)
    if days_ahead is not None:
        cutoff = datetime.utcnow() + timedelta(days=days_ahead)
        stmt = stmt.filter(DueDate.due_date <= cutoff)
    return list(
        db.session.execute(stmt.order_by(DueDate.due_date.asc())).scalars().all()
    )


def check_and_flag_overdue(tenant_id: Optional[str] = None) -> List[DueDate]:
    """Flag any still-``pending`` rows whose ``due_date`` has passed.

    Returns the list of newly-overdue rows. Commits only when at least one
    row was updated — matches the pre-split behaviour so scheduler runs on
    empty tenants stay silent.
    """
    stmt = db.select(DueDate).filter_by(status="pending").filter(
        DueDate.due_date < datetime.utcnow()
    )
    if tenant_id:
        stmt = stmt.filter_by(tenant_id=tenant_id)

    newly_overdue = list(db.session.execute(stmt).scalars().all())
    for dd in newly_overdue:
        dd.status = "overdue"
    if newly_overdue:
        db.session.commit()
    return newly_overdue
