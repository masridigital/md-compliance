"""REST endpoints for the compliance questionnaire wizard.

Blueprint: ``questionnaire_bp`` at ``/api/v1/compliance``.

All endpoints require an authenticated session and scope responses to
the caller's primary tenant via :class:`Authorizer`.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.masri.compliance import engine, framework_meta, service as qservice
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required
from flask_login import current_user

logger = logging.getLogger(__name__)

questionnaire_bp = Blueprint(
    "questionnaire_bp", __name__, url_prefix="/api/v1/compliance"
)


def _tenant_id() -> str | None:
    return Authorizer.get_tenant_id()


@questionnaire_bp.route("/frameworks", methods=["GET"])
@login_required
def list_frameworks():
    """List frameworks with a questionnaire bank available."""
    out = []
    for slug in framework_meta.list_available():
        meta = framework_meta.load(slug) or {}
        out.append({
            "slug": slug,
            "name": meta.get("name", slug),
            "description": meta.get("description", ""),
            "regulator": meta.get("regulator"),
            "has_questionnaire": bool(engine.get_bank(slug)),
            "has_exemptions": bool(meta.get("exemptions")),
        })
    return jsonify({"frameworks": out})


@questionnaire_bp.route("/<framework_slug>/questions", methods=["GET"])
@login_required
def get_questions(framework_slug: str):
    bank = engine.get_bank(framework_slug)
    if not bank:
        return jsonify({"error": "No questionnaire available for this framework"}), 404
    meta = framework_meta.load(framework_slug) or {}
    return jsonify({
        "framework": {
            "slug": framework_slug,
            "name": meta.get("name", framework_slug),
            "description": meta.get("description", ""),
            "regulator": meta.get("regulator"),
        },
        "questions": [q.to_dict() for q in bank],
        "exemptions": meta.get("exemptions", []),
    })


@questionnaire_bp.route("/<framework_slug>", methods=["GET"])
@login_required
def get_state(framework_slug: str):
    """Return the active questionnaire + exemption profile for this tenant."""
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400
    q = qservice.get_active_questionnaire(tid, framework_slug)
    profile = qservice.get_exemption_profile(tid, framework_slug)
    return jsonify({
        "questionnaire": q.as_dict() if q else None,
        "exemption_profile": profile.as_dict() if profile else None,
    })


@questionnaire_bp.route("/<framework_slug>/draft", methods=["POST"])
@login_required
def save_draft(framework_slug: str):
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400
    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {}) or {}
    project_id = body.get("project_id")
    q = qservice.save_draft(
        tid,
        framework_slug,
        answers,
        user_id=current_user.id if current_user.is_authenticated else None,
        project_id=project_id,
    )
    return jsonify({"questionnaire": q.as_dict()})


@questionnaire_bp.route("/<framework_slug>/submit", methods=["POST"])
@login_required
def submit(framework_slug: str):
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400
    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {}) or {}
    project_id = body.get("project_id")
    q, profile, errors = qservice.submit(
        tid,
        framework_slug,
        answers,
        user_id=current_user.id if current_user.is_authenticated else None,
        project_id=project_id,
    )
    if errors:
        return jsonify({"errors": errors}), 400
    try:
        from app.masri.compliance.deadlines import seed_deadlines_for_tenant
        seed_deadlines_for_tenant(tid, framework_slug)
    except Exception:
        logger.exception("Deadline seeding failed after questionnaire submit")
    return jsonify({
        "questionnaire": q.as_dict(),
        "exemption_profile": profile.as_dict(),
    })


@questionnaire_bp.route("/<framework_slug>/exemption/file", methods=["POST"])
@login_required
def mark_filed(framework_slug: str):
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400
    body = request.get_json(silent=True) or {}
    confirmation = body.get("confirmation")
    profile = qservice.mark_exemption_filed(tid, framework_slug, confirmation)
    if not profile:
        return jsonify({"error": "No exemption profile found"}), 404
    return jsonify({"exemption_profile": profile.as_dict()})


@questionnaire_bp.route("/deadlines", methods=["GET"])
@login_required
def list_deadlines():
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400
    from app.masri.compliance.deadlines import list_deadlines as _list

    framework_slug = request.args.get("framework")
    include_completed = (request.args.get("include_completed") or "").lower() in (
        "1",
        "true",
        "yes",
    )
    return jsonify({
        "deadlines": _list(
            tid,
            framework_slug=framework_slug,
            include_completed=include_completed,
        )
    })


@questionnaire_bp.route("/<framework_slug>/summary", methods=["GET"])
@login_required
def summary(framework_slug: str):
    """Compliance score + gap summary for this tenant/framework.

    Documents are loaded from :class:`ComplianceDocument` scoped to the
    tenant. Score honors the exemption profile if present.
    """
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400

    from app import db
    from app.masri.new_models import ComplianceDocument
    from app.masri.compliance.scoring import gap_items, score_for

    docs = db.session.execute(
        db.select(ComplianceDocument)
        .filter(ComplianceDocument.tenant_id == tid)
        .filter(ComplianceDocument.framework_slug == framework_slug)
    ).scalars().all()
    doc_projections = [
        {"doc_type": d.doc_type, "status": d.status} for d in docs
    ]

    profile = qservice.get_exemption_profile(tid, framework_slug)
    profile_dict = profile.as_dict() if profile else None
    return jsonify({
        "score": score_for(framework_slug, doc_projections, profile_dict),
        "gaps": gap_items(framework_slug, doc_projections, profile_dict),
        "exemption_profile": profile_dict,
    })
