"""Compliance score + gap analysis.

Score = approved docs / applicable sections (honoring exemption profile).
Only documents with ``status == 'approved'`` count. Draft docs show up in
the gap analysis as in-progress hints.
"""

from __future__ import annotations

from typing import Any

from app.masri.compliance import framework_meta
from app.masri.compliance.exemptions import applicable_sections


def score_for(
    framework_slug: str,
    documents: list[dict[str, Any]],
    exemption_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute score + per-section coverage summary.

    ``documents`` — list of dicts with at least ``doc_type`` and ``status``.
    Pass ``ComplianceDocument.as_dict()`` values or a shimmed projection.
    """
    meta = framework_meta.load(framework_slug) or {}
    sections = meta.get("sections", {})

    parts = applicable_sections(framework_slug, exemption_profile)
    covered: list[str] = []
    partial: list[str] = []
    missing: list[str] = []

    approved_types = {d["doc_type"] for d in documents if d.get("status") == "approved"}
    draft_types = {d["doc_type"] for d in documents if d.get("status") == "draft"}

    for code in parts["applicable"]:
        required = set(sections.get(code, {}).get("doc_types") or [])
        if not required:
            # Governance section with no doc_type requirement — skip from score.
            continue
        if approved_types & required:
            covered.append(code)
        elif draft_types & required:
            partial.append(code)
        else:
            missing.append(code)

    total = len(covered) + len(partial) + len(missing)
    score = int(round((len(covered) / total) * 100)) if total > 0 else 0

    return {
        "framework": framework_slug,
        "score": score,
        "total_scored_sections": total,
        "covered": covered,
        "partial": partial,
        "missing": missing,
        "exempt": parts["exempt"],
        "applicable_count": len(parts["applicable"]),
        "exempt_count": len(parts["exempt"]),
    }


def gap_items(
    framework_slug: str,
    documents: list[dict[str, Any]],
    exemption_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Flat list of missing/partial sections with metadata for the UI."""
    meta = framework_meta.load(framework_slug) or {}
    sections = meta.get("sections", {})
    score = score_for(framework_slug, documents, exemption_profile)
    gaps: list[dict[str, Any]] = []
    for code in score["missing"] + score["partial"]:
        s = sections.get(code, {})
        gaps.append({
            "section_code": code,
            "title": s.get("title", code),
            "severity": s.get("severity", "medium"),
            "doc_types": s.get("doc_types", []),
            "deadline_kind": s.get("deadline_kind"),
            "status": "partial" if code in score["partial"] else "missing",
        })
    # Sort critical > high > medium > low, then by code.
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    gaps.sort(key=lambda g: (rank.get(g["severity"], 9), g["section_code"]))
    return gaps
