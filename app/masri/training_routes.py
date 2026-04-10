"""
Masri Digital Compliance Platform — Training Module Routes

CRUD for training content, assignment management, completion tracking,
and evidence generation from completed training.

Blueprint: ``training_bp`` at url_prefix ``/api/v1/training``
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import db, limiter

logger = logging.getLogger(__name__)

training_bp = Blueprint("training_bp", __name__, url_prefix="/api/v1/training")


def _require_admin():
    """Abort 403 if the current user is not an admin."""
    if not current_user.super:
        from flask import abort
        abort(403, "Admin access required")


# ===========================================================================
# Training CRUD
# ===========================================================================

@training_bp.route("/", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_trainings():
    """GET /api/v1/training/ — List all training modules for this tenant."""
    from app.masri.new_models import Training
    tenant_id = Authorizer.get_tenant_id()
    trainings = db.session.execute(
        db.select(Training)
        .filter_by(tenant_id=tenant_id)
        .order_by(Training.date_added.desc())
    ).scalars().all()
    return jsonify([t.as_dict() for t in trainings])


@training_bp.route("/", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_training():
    """POST /api/v1/training/ — Create a new training module."""
    _require_admin()
    tenant_id = Authorizer.get_tenant_id()
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()[:255]
    if not title:
        return jsonify({"error": "Title is required"}), 400

    from app.masri.new_models import Training

    # Validate content_url: only allow http/https URLs, cap length
    content_url = (data.get("content_url") or "").strip()[:2048]
    if content_url and not content_url.startswith(("https://", "http://")):
        return jsonify({"error": "Content URL must be an http:// or https:// URL"}), 400

    # Cap description length
    description = (data.get("description") or "").strip()[:5000]

    # Sanitize framework_requirements: only allow simple alphanumeric strings
    raw_reqs = data.get("framework_requirements", [])
    framework_reqs = []
    if isinstance(raw_reqs, list):
        for req in raw_reqs:
            if isinstance(req, str) and len(req) <= 100:
                # Strip LIKE wildcards to prevent wildcard injection
                clean = req.replace("%", "").replace("_", " ").strip()
                if clean:
                    framework_reqs.append(clean)

    training = Training(
        tenant_id=tenant_id,
        title=title,
        description=description,
        content_type=data.get("content_type", "document"),
        content_url=content_url,
        frequency=data.get("frequency", "annual"),
        framework_requirements=framework_reqs,
        is_active=data.get("is_active", True),
    )
    db.session.add(training)
    db.session.commit()

    logger.info("Training created: %s (%s)", training.title, training.id)
    return jsonify(training.as_dict()), 201


@training_bp.route("/<string:training_id>", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_training(training_id):
    """GET /api/v1/training/<id> — Get training details."""
    from app.masri.new_models import Training
    tenant_id = Authorizer.get_tenant_id()
    training = db.session.execute(
        db.select(Training).filter_by(id=training_id, tenant_id=tenant_id)
    ).scalars().first()
    if not training:
        return jsonify({"error": "Training not found"}), 404
    return jsonify(training.as_dict())


@training_bp.route("/<string:training_id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_training(training_id):
    """PUT /api/v1/training/<id> — Update a training module."""
    _require_admin()
    from app.masri.new_models import Training
    tenant_id = Authorizer.get_tenant_id()
    training = db.session.execute(
        db.select(Training).filter_by(id=training_id, tenant_id=tenant_id)
    ).scalars().first()
    if not training:
        return jsonify({"error": "Training not found"}), 404

    data = request.get_json(silent=True) or {}

    # Validate content_url if provided
    if "content_url" in data:
        content_url = (data["content_url"] or "").strip()
        if content_url and not content_url.startswith(("https://", "http://")):
            return jsonify({"error": "Content URL must be an http:// or https:// URL"}), 400
        data["content_url"] = content_url

    # Sanitize framework_requirements if provided
    if "framework_requirements" in data:
        raw_reqs = data.get("framework_requirements", [])
        framework_reqs = []
        if isinstance(raw_reqs, list):
            for req in raw_reqs:
                if isinstance(req, str) and len(req) <= 100:
                    clean = req.replace("%", "").replace("_", " ").strip()
                    if clean:
                        framework_reqs.append(clean)
        training.framework_requirements = framework_reqs

    for field in ("title", "description", "content_type", "content_url", "frequency", "is_active"):
        if field in data:
            setattr(training, field, data[field])
    db.session.commit()
    return jsonify(training.as_dict())


@training_bp.route("/<string:training_id>", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def delete_training(training_id):
    """DELETE /api/v1/training/<id> — Delete a training module."""
    _require_admin()
    from app.masri.new_models import Training
    tenant_id = Authorizer.get_tenant_id()
    training = db.session.execute(
        db.select(Training).filter_by(id=training_id, tenant_id=tenant_id)
    ).scalars().first()
    if not training:
        return jsonify({"error": "Training not found"}), 404

    db.session.delete(training)
    db.session.commit()
    return jsonify({"deleted": True})


# ===========================================================================
# Assignments
# ===========================================================================

@training_bp.route("/<string:training_id>/assignments", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_assignments(training_id):
    """GET /api/v1/training/<id>/assignments — List assignments."""
    from app.masri.new_models import TrainingAssignment
    tenant_id = Authorizer.get_tenant_id()
    assignments = db.session.execute(
        db.select(TrainingAssignment)
        .filter_by(training_id=training_id, tenant_id=tenant_id)
        .order_by(TrainingAssignment.assigned_date.desc())
    ).scalars().all()
    return jsonify([a.as_dict() for a in assignments])


@training_bp.route("/<string:training_id>/assign", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def assign_training(training_id):
    """POST /api/v1/training/<id>/assign — Assign training to users."""
    _require_admin()
    from app.masri.new_models import Training, TrainingAssignment
    tenant_id = Authorizer.get_tenant_id()

    training = db.session.execute(
        db.select(Training).filter_by(id=training_id, tenant_id=tenant_id)
    ).scalars().first()
    if not training:
        return jsonify({"error": "Training not found"}), 404

    data = request.get_json(silent=True) or {}
    emails = data.get("emails", [])
    if not emails or not isinstance(emails, list):
        return jsonify({"error": "emails list is required"}), 400

    due_date = None
    if data.get("due_date"):
        try:
            due_date = datetime.fromisoformat(data["due_date"])
        except (ValueError, TypeError):
            pass

    created = 0
    for email_entry in emails:
        email = (email_entry if isinstance(email_entry, str) else email_entry.get("email", "")).strip().lower()
        name = email_entry.get("name", "") if isinstance(email_entry, dict) else ""
        if not email or "@" not in email:
            continue

        # Check if already assigned
        existing = db.session.execute(
            db.select(TrainingAssignment).filter_by(
                training_id=training_id, tenant_id=tenant_id, user_email=email
            ).filter(TrainingAssignment.completed_date.is_(None))
        ).scalars().first()
        if existing:
            continue

        assignment = TrainingAssignment(
            tenant_id=tenant_id,
            training_id=training_id,
            user_email=email,
            user_name=name,
            due_date=due_date,
        )
        db.session.add(assignment)
        created += 1

    db.session.commit()
    return jsonify({"assigned": created}), 201


@training_bp.route("/assignments/<string:assignment_id>/complete", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def complete_assignment(assignment_id):
    """POST /api/v1/training/assignments/<id>/complete — Mark assignment complete."""
    from app.masri.new_models import TrainingAssignment
    tenant_id = Authorizer.get_tenant_id()
    assignment = db.session.execute(
        db.select(TrainingAssignment).filter_by(id=assignment_id, tenant_id=tenant_id)
    ).scalars().first()
    if not assignment:
        return jsonify({"error": "Assignment not found"}), 404

    if assignment.completed_date:
        return jsonify({"error": "Already completed"}), 400

    data = request.get_json(silent=True) or {}
    assignment.completed_date = datetime.utcnow()
    if data.get("score") is not None:
        try:
            score = int(data["score"])
            assignment.score = max(0, min(score, 100))
        except (ValueError, TypeError):
            pass

    db.session.commit()

    # Auto-generate evidence from completed training
    try:
        _generate_training_evidence(assignment)
    except Exception:
        logger.exception("Training evidence generation failed for %s", assignment_id)

    return jsonify(assignment.as_dict())


# ===========================================================================
# Dashboard / Stats
# ===========================================================================

@training_bp.route("/dashboard", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def training_dashboard():
    """GET /api/v1/training/dashboard — Training completion stats."""
    from app.masri.new_models import Training, TrainingAssignment
    tenant_id = Authorizer.get_tenant_id()

    trainings = db.session.execute(
        db.select(Training).filter_by(tenant_id=tenant_id, is_active=True)
    ).scalars().all()

    total_assigned = 0
    total_completed = 0
    overdue = 0
    now = datetime.utcnow()

    training_ids = [t.id for t in trainings]
    assignments = db.session.execute(
        db.select(TrainingAssignment).filter(
            TrainingAssignment.training_id.in_(training_ids),
            TrainingAssignment.tenant_id == tenant_id,
        )
    ).scalars().all() if training_ids else []

    for a in assignments:
        total_assigned += 1
        if a.completed_date:
            total_completed += 1
        elif a.due_date and a.due_date < now:
            overdue += 1

    completion_rate = (total_completed / total_assigned * 100) if total_assigned else 0

    return jsonify({
        "total_trainings": len(trainings),
        "total_assigned": total_assigned,
        "total_completed": total_completed,
        "overdue": overdue,
        "completion_rate": round(completion_rate, 1),
    })


# ===========================================================================
# Built-in Templates
# ===========================================================================

@training_bp.route("/templates", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_templates():
    """GET /api/v1/training/templates — Built-in training templates."""
    return jsonify(_BUILT_IN_TEMPLATES)


@training_bp.route("/templates/<string:template_id>/create", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def create_from_template(template_id):
    """POST /api/v1/training/templates/<id>/create — Create training from built-in template."""
    _require_admin()
    template = next((t for t in _BUILT_IN_TEMPLATES if t["id"] == template_id), None)
    if not template:
        return jsonify({"error": "Template not found"}), 404

    from app.masri.new_models import Training
    tenant_id = Authorizer.get_tenant_id()

    training = Training(
        tenant_id=tenant_id,
        title=template["title"],
        description=template["description"],
        content_type=template["content_type"],
        frequency=template["frequency"],
        framework_requirements=template.get("framework_requirements", []),
        is_active=True,
    )
    db.session.add(training)
    db.session.commit()
    return jsonify(training.as_dict()), 201


# ===========================================================================
# Helpers
# ===========================================================================

def _generate_training_evidence(assignment):
    """Generate evidence record from a completed training assignment."""
    from app.models import ProjectEvidence, Project, EvidenceAssociation, ProjectSubControl
    from app.masri.new_models import Training

    training = db.session.get(Training, assignment.training_id)
    if not training or not training.framework_requirements:
        return

    # Find projects for this tenant
    projects = db.session.execute(
        db.select(Project).filter_by(tenant_id=assignment.tenant_id)
    ).scalars().all()

    for project in projects:
        evidence = ProjectEvidence(
            project_id=project.id,
            title=f"Training Completion: {training.title}",
            description=(
                f"Employee {assignment.user_name or assignment.user_email} "
                f"completed training '{training.title}' on "
                f"{assignment.completed_date.strftime('%Y-%m-%d')}."
                + (f" Score: {assignment.score}%" if assignment.score is not None else "")
            ),
            tier="complete",
            source="training_module",
            exhibit_ref=f"Training: {training.title} | {assignment.user_email}",
        )
        db.session.add(evidence)
        db.session.flush()

        # Link to applicable subcontrols based on framework_requirements
        for req in training.framework_requirements:
            if isinstance(req, str):
                # Match subcontrols by keyword
                subs = db.session.execute(
                    db.select(ProjectSubControl)
                    .filter_by(project_id=project.id)
                    .filter(
                        ProjectSubControl.name.ilike(f"%{req}%")
                        | ProjectSubControl.description.ilike(f"%{req}%")
                    )
                ).scalars().all()
                for sub in subs[:3]:
                    assoc = EvidenceAssociation(
                        evidence_id=evidence.id,
                        sub_control_id=sub.id,
                    )
                    db.session.add(assoc)

    db.session.commit()


_BUILT_IN_TEMPLATES = [
    {
        "id": "ftc_safeguards_awareness",
        "title": "FTC Safeguards Rule — Security Awareness Training",
        "description": (
            "Annual security awareness training covering the FTC Safeguards Rule requirements: "
            "identifying and reporting security threats, safe handling of customer information, "
            "password hygiene, phishing awareness, and incident reporting procedures."
        ),
        "content_type": "document",
        "frequency": "annual",
        "framework_requirements": [
            "security awareness",
            "training",
            "employee training",
            "information security",
        ],
    },
    {
        "id": "hipaa_security_awareness",
        "title": "HIPAA Security Awareness Training",
        "description": (
            "Annual training on HIPAA Security Rule requirements: protecting ePHI, "
            "recognizing social engineering attacks, proper use of workstations and devices, "
            "password management, and breach reporting obligations."
        ),
        "content_type": "document",
        "frequency": "annual",
        "framework_requirements": [
            "security awareness",
            "training",
            "workforce security",
            "information access management",
        ],
    },
    {
        "id": "general_security_awareness",
        "title": "General Security Awareness Training",
        "description": (
            "Comprehensive security awareness training covering: phishing and social engineering, "
            "password best practices, multi-factor authentication, data classification and handling, "
            "physical security, remote work security, and incident reporting."
        ),
        "content_type": "document",
        "frequency": "annual",
        "framework_requirements": [
            "security awareness",
            "training",
            "access control",
            "security training",
        ],
    },
    {
        "id": "pci_dss_awareness",
        "title": "PCI DSS Security Awareness Training",
        "description": (
            "Annual training on PCI DSS requirements for handling cardholder data: "
            "data protection standards, acceptable use policies, secure handling procedures, "
            "incident response, and compliance responsibilities."
        ),
        "content_type": "document",
        "frequency": "annual",
        "framework_requirements": [
            "security awareness",
            "training",
            "cardholder data",
            "security policy",
        ],
    },
]
