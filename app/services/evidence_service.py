"""
Evidence service — DB mutations for ProjectEvidence + EvidenceAssociation.

Covers project-level and subcontrol-level evidence lifecycles. See
:mod:`app.services` for conventions.

Note: ``Project.create_evidence`` / ``ProjectEvidence.update`` /
``ProjectEvidence.delete`` own their own ``db.session.commit()`` calls
internally — this module delegates to them and preserves that
commit-on-behalf semantics rather than wrapping in a double-commit.
Subcontrol-level association toggles DO commit here so call sites stay
uniform.
"""

from typing import Any, Iterable, Mapping, Optional

from app import db
from app.models import ProjectEvidence


# ── Queries ──────────────────────────────────────────────────────────────

def list_for_project(project) -> list:
    """Return all evidence records attached to ``project`` (list, not query)."""
    return project.evidence.all()


def list_for_subcontrol(subcontrol) -> list:
    """Return all evidence linked to a specific subcontrol.

    ``ProjectSubControl.evidence`` is a ``lazy="select"`` list after E5,
    so callers just receive it directly.
    """
    return subcontrol.evidence


def get_file_bytes(evidence: ProjectEvidence) -> bytes:
    """Return the raw bytes for an evidence file attachment."""
    return evidence.get_file(as_blob=True)


def groupings_for_project(project) -> list:
    """Return evidence grouped by control for a project.

    Wraps ``Project.evidence_groupings()``; returns the values in
    insertion order so the view can serialise directly.
    """
    groups = project.evidence_groupings() or {}
    return list(groups.values())


# ── Mutations: project-level evidence lifecycle ─────────────────────────

def create_for_project(
    project,
    *,
    name: Optional[str],
    description: Optional[str],
    content: Optional[str],
    owner,
    file=None,
    associate_with: Optional[Iterable[str]] = None,
) -> ProjectEvidence:
    """Create a new evidence record under ``project``.

    Delegates to ``Project.create_evidence`` which persists + commits.
    When ``associate_with`` is provided, the evidence is linked to the
    given subcontrol IDs in the same call.
    """
    return project.create_evidence(
        name=name,
        content=content,
        description=description,
        owner_id=owner.id,
        file=file,
        associate_with=list(associate_with) if associate_with else [],
    )


def create_for_subcontrol(
    subcontrol,
    *,
    name: Optional[str],
    description: Optional[str],
    content: Optional[str],
    owner,
    file=None,
) -> ProjectEvidence:
    """Create evidence under the subcontrol's parent project + link it.

    Convenience wrapper — equivalent to ``create_for_project`` with
    ``associate_with=[subcontrol.id]``.
    """
    return create_for_project(
        subcontrol.project,
        name=name,
        description=description,
        content=content,
        owner=owner,
        file=file,
        associate_with=[subcontrol.id],
    )


def update(evidence: ProjectEvidence, form: Mapping[str, Any], *, file=None) -> ProjectEvidence:
    """Apply an evidence update (plus optional file replacement).

    ``ProjectEvidence.update`` commits internally.
    """
    evidence.update(
        name=form.get("name"),
        description=form.get("description"),
        content=form.get("content"),
        collected_on=form.get("collected"),
        file=file,
    )
    return evidence


def delete(evidence: ProjectEvidence) -> None:
    """Delete an evidence record (removes the file side-effectfully).

    ``ProjectEvidence.delete`` handles file cleanup + commit.
    """
    evidence.delete()


def remove_file(evidence: ProjectEvidence) -> None:
    """Remove the attached file from an evidence record (keeps the record)."""
    evidence.remove_file()


# ── Mutations: association surface ──────────────────────────────────────

def associate_with_controls(evidence: ProjectEvidence, control_ids: Iterable[str]) -> None:
    """Re-associate this evidence with the given subcontrol IDs.

    Replaces the full association set (matches model semantics).
    """
    evidence.associate_with_controls(list(control_ids))


def add_evidence_to_subcontrol(subcontrol, evidence_ids: Iterable[str]):
    """Add evidence to a subcontrol's association set.

    Additive — existing associations are preserved. Duplicates are a
    no-op at the ``EvidenceAssociation.add`` layer.
    """
    subcontrol.associate_with_evidence(list(evidence_ids))
    return subcontrol


def remove_evidence_ids_from_subcontrol(subcontrol, evidence_ids: Iterable[str]):
    """Remove evidence IDs from a subcontrol's association set."""
    subcontrol.disassociate_with_evidence(list(evidence_ids))
    return subcontrol


def remove_evidence_from_subcontrol(subcontrol, evidence: ProjectEvidence) -> None:
    """Remove a single evidence instance from a subcontrol's list. Commits.

    Distinct from ``remove_evidence_ids_from_subcontrol`` (batch-by-ID);
    this takes the ORM instance and uses the relationship collection
    directly, matching the per-item DELETE endpoint semantics.
    """
    if evidence in subcontrol.evidence:
        subcontrol.evidence.remove(evidence)
        db.session.commit()
