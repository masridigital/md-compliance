"""REST endpoints for compliance documents + templates.

Blueprint: ``compliance_docs_bp`` at ``/api/v1/compliance-docs``.
"""

from __future__ import annotations

import logging
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user

from app import db, limiter
from app.masri.compliance import document_service, framework_meta
from app.masri.new_models import (
    ComplianceDocument,
    ComplianceDocumentVersion,
    DocumentTemplate,
)
from app.masri.storage_router import get_file
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required

logger = logging.getLogger(__name__)

compliance_docs_bp = Blueprint(
    "compliance_docs_bp", __name__, url_prefix="/api/v1/compliance-docs"
)


def _tenant_id() -> str | None:
    return Authorizer.get_tenant_id()


# ── Documents ─────────────────────────────────────────────────────────────

@compliance_docs_bp.route("/documents", methods=["GET"])
@login_required
def list_documents():
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400
    framework_slug = request.args.get("framework")
    docs = document_service.list_documents(tid, framework_slug=framework_slug)
    return jsonify({"documents": [d.as_dict() for d in docs]})


@compliance_docs_bp.route("/documents/generate", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def generate_document():
    """Generate a new compliance document from scratch or a template."""
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400

    body = request.get_json(silent=True) or {}
    doc_type = body.get("doc_type")
    framework_slug = body.get("framework_slug")
    template_id = body.get("template_id")
    title = body.get("title")
    project_id = body.get("project_id")

    try:
        if template_id:
            doc = document_service.generate_from_template(
                tenant_id=tid,
                template_id=template_id,
                title=title,
                project_id=project_id,
                user_id=current_user.id,
            )
        else:
            if not doc_type:
                return jsonify({"error": "doc_type is required"}), 400
            doc = document_service.generate_from_scratch(
                tenant_id=tid,
                doc_type=doc_type,
                framework_slug=framework_slug,
                title=title,
                project_id=project_id,
                user_id=current_user.id,
            )
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except RuntimeError as re:
        # Typically LLMService: not configured, rate limit, budget exhausted
        return jsonify({"error": str(re)}), 503
    except Exception:
        logger.exception("Document generation failed")
        return jsonify({"error": "Document generation failed"}), 500

    return jsonify({"document": doc.as_dict()})


@compliance_docs_bp.route("/documents/<doc_id>", methods=["GET"])
@login_required
def get_document(doc_id: str):
    tid = _tenant_id()
    doc = db.session.get(ComplianceDocument, doc_id)
    if not doc or doc.tenant_id != tid:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"document": doc.as_dict()})


@compliance_docs_bp.route("/documents/<doc_id>/download", methods=["GET"])
@login_required
def download_document(doc_id: str):
    tid = _tenant_id()
    doc = db.session.get(ComplianceDocument, doc_id)
    if not doc or doc.tenant_id != tid:
        return jsonify({"error": "Not found"}), 404
    version = doc.latest_version()
    if not version:
        return jsonify({"error": "No versions yet"}), 404
    data = get_file(version.storage_key, role="reports")
    if not data:
        return jsonify({"error": "File missing from storage"}), 404
    safe_name = doc.title.replace("/", "-") + ".docx"
    return send_file(
        BytesIO(data),
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        as_attachment=True,
        download_name=safe_name,
    )


@compliance_docs_bp.route("/documents/<doc_id>/approve", methods=["POST"])
@login_required
def approve_document(doc_id: str):
    from datetime import datetime

    tid = _tenant_id()
    doc = db.session.get(ComplianceDocument, doc_id)
    if not doc or doc.tenant_id != tid:
        return jsonify({"error": "Not found"}), 404
    doc.status = "approved"
    doc.approved_by_user_id = current_user.id
    doc.approved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"document": doc.as_dict()})


# ── Templates ─────────────────────────────────────────────────────────────

@compliance_docs_bp.route("/templates", methods=["GET"])
@login_required
def list_templates():
    tid = _tenant_id()
    templates = document_service.list_templates(tid)
    return jsonify({"templates": [t.as_dict() for t in templates]})


@compliance_docs_bp.route("/templates", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def upload_template():
    tid = _tenant_id()
    if not tid:
        return jsonify({"error": "No tenant context"}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".docx"):
        return jsonify({"error": "Only .docx templates are supported"}), 400

    docx_bytes = file.read()
    if not docx_bytes:
        return jsonify({"error": "Empty file"}), 400

    doc_type = request.form.get("doc_type")
    if not doc_type:
        return jsonify({"error": "doc_type is required"}), 400

    is_global_str = (request.form.get("is_global") or "").lower()
    is_global = is_global_str in ("true", "1", "yes") and getattr(
        current_user, "super", False
    )

    try:
        template = document_service.upload_template(
            tenant_id=tid,
            docx_bytes=docx_bytes,
            file_name=file.filename,
            doc_type=doc_type,
            name=request.form.get("name") or file.filename,
            description=request.form.get("description"),
            framework_slug=request.form.get("framework_slug"),
            is_global=is_global,
            user_id=current_user.id,
        )
    except Exception:
        logger.exception("Template upload failed")
        return jsonify({"error": "Upload failed"}), 500

    return jsonify({"template": template.as_dict()})


@compliance_docs_bp.route("/templates/<template_id>", methods=["GET"])
@login_required
def get_template(template_id: str):
    tid = _tenant_id()
    template = db.session.get(DocumentTemplate, template_id)
    if not template:
        return jsonify({"error": "Not found"}), 404
    if not template.is_global and template.tenant_id != tid:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"template": template.as_dict()})


@compliance_docs_bp.route("/templates/<template_id>/mapping", methods=["PUT"])
@login_required
def update_template_mapping(template_id: str):
    tid = _tenant_id()
    template = db.session.get(DocumentTemplate, template_id)
    if not template:
        return jsonify({"error": "Not found"}), 404
    if template.is_global and not getattr(current_user, "super", False):
        return jsonify({"error": "Forbidden"}), 403
    if not template.is_global and template.tenant_id != tid:
        return jsonify({"error": "Forbidden"}), 403

    body = request.get_json(silent=True) or {}
    mapping = body.get("placeholder_map") or {}
    if not isinstance(mapping, dict):
        return jsonify({"error": "placeholder_map must be an object"}), 400

    known = set(template.placeholders or [])
    mapping = {k: v for k, v in mapping.items() if k in known}
    template.placeholder_map = mapping
    db.session.commit()
    return jsonify({"template": template.as_dict()})


@compliance_docs_bp.route("/templates/<template_id>", methods=["DELETE"])
@login_required
def delete_template(template_id: str):
    tid = _tenant_id()
    template = db.session.get(DocumentTemplate, template_id)
    if not template:
        return jsonify({"error": "Not found"}), 404
    if template.is_global and not getattr(current_user, "super", False):
        return jsonify({"error": "Forbidden"}), 403
    if not template.is_global and template.tenant_id != tid:
        return jsonify({"error": "Forbidden"}), 403
    db.session.delete(template)
    db.session.commit()
    return jsonify({"ok": True})


# ── Metadata helpers ──────────────────────────────────────────────────────

@compliance_docs_bp.route("/doc-types", methods=["GET"])
@login_required
def list_doc_types():
    framework_slug = request.args.get("framework")
    if framework_slug:
        return jsonify({"doc_types": document_service.doc_types_for(framework_slug)})
    # Union across all frameworks with metadata
    types: set[str] = set()
    for slug in framework_meta.list_available():
        for dt in document_service.doc_types_for(slug):
            types.add(dt)
    return jsonify({"doc_types": sorted(types)})
