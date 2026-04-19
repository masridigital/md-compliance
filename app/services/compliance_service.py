"""
Compliance service — framework / policy / control lifecycle.

Covers the compliance-domain mutations that sit above the
project-specific ones in :mod:`project_service`: tenant-scoped
framework + policy + control CRUD, policy versions, and the bridges
between controls / subcontrols and projects.

See :mod:`app.services` for conventions.
"""

from typing import Any, Mapping, Optional

from app import db
from app.models import Control, Policy


# ── Framework queries + seeding ──────────────────────────────────────────

def list_frameworks_for_tenant(tenant) -> list:
    """Return frameworks registered for ``tenant``."""
    return tenant.frameworks.all()


def reload_base_frameworks(tenant) -> None:
    """Re-seed the built-in framework + control library for a tenant."""
    tenant.create_base_frameworks()


# ── Policy queries + creation (tenant-scoped) ───────────────────────────

def list_policies_for_tenant(tenant) -> list:
    """Return all tenant-scoped policies."""
    return tenant.policies.all()


def create_tenant_policy(tenant, data: Mapping[str, Any]) -> Policy:
    """Create a new tenant-scoped ``Policy`` and commit."""
    policy = Policy(
        name=data["name"],
        description=data.get("description"),
        ref_code=data.get("code"),
    )
    tenant.policies.append(policy)
    db.session.commit()
    return policy


def reload_base_policies(tenant) -> None:
    """Re-seed the built-in policy templates for a tenant."""
    tenant.create_base_policies()


# ── Policy mutations (generic) ───────────────────────────────────────────

def update_policy(policy: Policy, data: Mapping[str, Any]) -> Policy:
    """Apply an update payload to a ``Policy`` and commit."""
    policy.name = data["name"]
    policy.ref_code = data["ref_code"]
    policy.description = data["description"]
    policy.template = data["template"]
    policy.content = data["content"]
    db.session.commit()
    return policy


def delete_policy(policy: Policy) -> None:
    """Delete a policy and commit."""
    db.session.delete(policy)
    db.session.commit()


# ── Control mutations (generic) ─────────────────────────────────────────

def create_tenant_control(tenant, payload: Mapping[str, Any]) -> None:
    """Create a custom control under a tenant.

    Delegates to ``Control.create`` which owns the framework-association
    logic. The model helper commits on success.
    """
    Control.create(payload, tenant.id)


def soft_delete_control(control: Control) -> None:
    """Hide a control from all projects without destroying rows.

    Sets ``visible = False`` + commits. Matches the historical semantic
    of the ``DELETE /controls/<cid>`` endpoint which is actually a soft
    delete.
    """
    control.visible = False
    db.session.commit()


# ── Project-scoped policy lifecycle ──────────────────────────────────────

def list_policies_for_project(project) -> list:
    """Return policies attached to ``project``."""
    return project.policies.all()


def create_policy_for_project(project, data: Mapping[str, Any]):
    """Create a new ``ProjectPolicy`` under ``project`` and commit.

    ``Project.create_policy`` owns the commit.
    """
    return project.create_policy(
        name=data.get("name"),
        description=data.get("description"),
        template=data.get("template"),
    )


def update_project_policy(policy, data: Mapping[str, Any]):
    """Apply a ``ProjectPolicyUpdateSchema`` payload to a project policy.

    ``ProjectPolicy.update`` owns the commit.
    """
    return policy.update(
        name=data.get("name"),
        description=data.get("description"),
        reviewer=data.get("reviewer"),
    )


def delete_project_policy(policy, project, ppid: str) -> None:
    """Remove a policy from a project.

    ``Project.remove_policy`` cascades version deletes + commits.
    """
    project.remove_policy(ppid)


# ── Policy versions ──────────────────────────────────────────────────────

def create_policy_version(policy, content: str):
    """Append a new version to a policy. Delegates + commits in the model."""
    return policy.add_version(content or "")


def get_policy_version(policy, version, as_dict: bool = True):
    """Fetch a specific version from a policy."""
    return policy.get_version(version, as_dict=as_dict)


def delete_policy_version(policy, version) -> None:
    """Remove a version from a policy."""
    policy.delete_version(version)


def update_policy_version(policy, version, data: Mapping[str, Any]):
    """Apply a ``PolicyVersionUpdateSchema`` payload to a version."""
    return policy.update_version(
        version=version,
        content=data.get("content"),
        status=data.get("status"),
        publish=data.get("publish"),
    )


# ── Project ↔ control bridge ─────────────────────────────────────────────

def add_control_to_project(project, control):
    """Add a ``Control`` to a project. Commits via ``Project.add_control``."""
    project.add_control(control)
    return control


def remove_control_from_project(project, cid: str) -> None:
    """Remove a control from a project by id."""
    project.remove_control(cid)


# ── Project-control field mutations ──────────────────────────────────────

def set_review_status(project_control, status: str):
    """Persist a review_status update on a ``ProjectControl`` and commit."""
    project_control.review_status = (status or "").lower()
    db.session.commit()
    return project_control


def update_control_notes(project_control, notes: Optional[str]):
    """Replace the notes field on a ``ProjectControl`` and commit.

    Empty string is accepted so callers can clear notes.
    """
    project_control.notes = notes
    db.session.commit()
    return project_control


def set_control_applicability(project_control, applicable: bool):
    """Flip the applicability of a ``ProjectControl`` + cascade to subs.

    ``ProjectControl.set_applicability`` iterates subs + commits.
    """
    project_control.set_applicability(applicable)
    return project_control


def update_subcontrol(subcontrol, payload: Mapping[str, Any]):
    """Apply a ``SubcontrolUpdateSchema`` payload. Commits in the model."""
    return subcontrol.update(
        applicable=payload.get("applicable"),
        implemented=payload.get("implemented"),
        notes=payload.get("notes"),
        context=payload.get("context"),
        evidence=payload.get("evidence"),
        owner_id=payload.get("owner_id"),
    )
