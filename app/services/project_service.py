"""
Project service — DB mutations for Project aggregates.

See :mod:`app.services` for conventions. Views pass already-authorised
:class:`Project` instances (obtained via ``Authorizer``); this module
returns the same instance after committing so the view can serialise.
"""

from typing import Any, Mapping, Optional

from flask import abort

from app import db
from app.models import Project
from app.utils import misc


def list_for_user(user, tenant):
    """Return the list of projects in ``tenant`` that ``user`` can access.

    Pure query — no mutations. Moved here so that ``get_projects_in_tenant``
    in the view layer is a one-line delegation.
    """
    return user.get_projects(tenant.id)


def get_serializable(project: Project, with_summary: bool = False) -> dict:
    """Return ``project.as_dict()`` with the flags the view would have applied.

    Thin helper — lets views avoid passing kwargs through the service /
    model boundary when the call is trivial.
    """
    return project.as_dict(with_summary=with_summary)


def update_basic(
    project: Project,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Project:
    """Update the always-editable basic fields on a project. Commits.

    ``name`` and ``description`` are each applied only when truthy —
    matching the historical behaviour of the ``update_project`` view.
    """
    if name:
        project.name = name
    if description:
        project.description = description
    db.session.commit()
    return project


def update_settings(project: Project, data: Mapping[str, Any]) -> Project:
    """Apply a validated ``ProjectSettingsSchema`` payload. Commits.

    Preserves the historical semantics from ``update_settings_in_project``
    in the view layer:

    - ``name`` / ``description`` / ``notes`` apply when present.
    - Boolean auditor/policy toggles apply only when the payload value is
      a real ``bool`` (``None`` leaves the existing value alone).
    """
    if data.get("name"):
        project.name = data["name"]
    if data.get("description"):
        project.description = data["description"]
    if data.get("notes") is not None:
        project.notes = data["notes"]

    for field in (
        "auditor_enabled",
        "can_auditor_read_scratchpad",
        "can_auditor_write_scratchpad",
        "can_auditor_read_comments",
        "can_auditor_write_comments",
        "policies_require_cc",
    ):
        value = data.get(field)
        if isinstance(value, bool):
            setattr(project, field, value)

    db.session.commit()
    return project


def delete(project: Project) -> None:
    """Delete the project and cascade children. Commits."""
    db.session.delete(project)
    db.session.commit()


def create_for_tenant(tenant, payload: Mapping[str, Any], owner) -> bool:
    """Create a project under ``tenant`` owned by ``owner``.

    Thin wrapper around the legacy ``app.utils.misc.project_creation``
    helper — kept as-is during the E2 pilot to avoid disturbing the
    framework/control seeding path. The helper already commits.

    Returns ``True`` on success, or aborts with the appropriate HTTP
    error code on failure. A ``False`` return historically mapped to a
    400 in the view — preserved for backward compatibility.
    """
    return misc.project_creation(tenant, payload, owner)


def set_notes(project: Project, text: Optional[str]) -> Project:
    """Set the project's notes/scratchpad field to ``text`` and commit.

    The ``notes`` column is a single shared string — both the
    ``/projects/<id>/scratchpad`` endpoint and the settings panel's
    "Project Notes" field back onto it. Empty string is allowed so
    users can clear their notes.
    """
    if text is not None:
        project.notes = text
        db.session.commit()
    return project
