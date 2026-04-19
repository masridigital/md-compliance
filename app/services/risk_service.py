"""
Risk service — DB mutations for RiskRegister + RiskComment.

Covers both project-scoped and tenant-scoped risk lifecycles. See
:mod:`app.services` for conventions. Views pass already-authorised
domain objects; services commit and return domain instances.
"""

from typing import Any, Mapping, Optional

from flask import abort

from app import db
from app.models import RiskComment, RiskRegister


# ── Queries ──────────────────────────────────────────────────────────────

def list_for_project(project) -> list:
    """Return all risks attached to ``project``.

    Reads through the ``project.risks`` relationship, which replaces the
    inline raw-SQL query the view used to run.
    """
    return (
        db.session.execute(
            db.select(RiskRegister).filter(RiskRegister.project_id == project.id)
        )
        .scalars()
        .all()
    )


def list_for_tenant(tenant) -> list:
    """Return all risks attached to ``tenant``."""
    return (
        db.session.execute(
            db.select(RiskRegister).filter(RiskRegister.tenant_id == tenant.id)
        )
        .scalars()
        .all()
    )


def _find_in_project(project, rid: str) -> RiskRegister:
    """Locate a risk by id within a project. Aborts 404 if not found.

    Internal helper used by the project-scoped update endpoint.
    """
    risk = (
        db.session.execute(
            db.select(RiskRegister)
            .filter(RiskRegister.project_id == project.id)
            .filter(RiskRegister.id == rid)
        )
        .scalars()
        .first()
    )
    if not risk:
        abort(404)
    return risk


# ── Project-scoped mutations ─────────────────────────────────────────────

def create_for_project(project, data: Mapping[str, Any]) -> RiskRegister:
    """Create a risk attached to ``project`` and commit.

    Delegates to ``Project.create_risk`` which already commits — the
    service wrapper keeps the call site shape consistent with the rest
    of the risk surface.
    """
    return project.create_risk(
        title=data.get("title"),
        description=data.get("description"),
        status=data.get("status"),
        risk=data.get("risk"),
        priority=data.get("priority"),
    )


def update_in_project(project, rid: str, data: Mapping[str, Any]) -> RiskRegister:
    """Update a project-scoped risk by id. Commits."""
    risk = _find_in_project(project, rid)
    risk.title = data.get("title")
    risk.description = data.get("description")
    risk.status = data.get("status")
    risk.risk = data.get("risk")
    risk.priority = data.get("priority")
    db.session.commit()
    return risk


# ── Tenant-scoped mutations ──────────────────────────────────────────────

def create_for_tenant(tenant, data: Mapping[str, Any]) -> RiskRegister:
    """Create a tenant-scoped risk and commit.

    ``Tenant.create_risk`` returns a detached ``RiskRegister`` — this
    function adds it to the session and commits.
    """
    risk = tenant.create_risk(
        title=data.get("title"),
        description=data.get("description"),
        remediation=data.get("remediation"),
        tags=data.get("tags"),
        assignee=data.get("assignee"),
        enabled=data.get("enabled"),
        status=data.get("status"),
        risk=data.get("risk"),
        priority=data.get("priority"),
        vendor_id=data.get("vendor_id"),
    )
    db.session.add(risk)
    db.session.commit()
    return risk


def update(risk: RiskRegister, data: Mapping[str, Any], *, user=None) -> RiskRegister:
    """Apply a field-level update via ``RiskRegister.update`` and log.

    ``RiskRegister.update`` owns the schema-level mutation (including
    encrypted title re-hashing). Service commits via ``Tenant.add_log``.
    """
    risk.update(**data)
    risk.tenant.add_log(
        message=f"Updated risk: {risk.title}",
        namespace="risks",
        action="update",
        user_id=(user.id if user is not None else None),
    )
    return risk


def delete(risk: RiskRegister) -> None:
    """Delete a risk and commit."""
    db.session.delete(risk)
    db.session.commit()


def add_comment(risk: RiskRegister, message: str, *, owner) -> RiskComment:
    """Append a comment to ``risk`` and commit. Writes an audit log entry."""
    tenant = risk.tenant
    comment = RiskComment(
        message=message,
        owner_id=owner.id,
        tenant_id=tenant.id,
    )
    risk.comments.append(comment)
    db.session.commit()
    tenant.add_log(
        message=f"Added comment for risk:{risk.id}",
        namespace="comments",
        action="create",
        user_id=owner.id,
    )
    return comment


# ── Auditor-feedback → risk bridge ───────────────────────────────────────

def create_from_feedback(feedback) -> None:
    """Promote an ``AuditorFeedback`` item into a risk register entry.

    Delegates to ``AuditorFeedback.create_risk_record`` which owns the
    duplicate-detection + encryption logic.
    """
    feedback.create_risk_record()
