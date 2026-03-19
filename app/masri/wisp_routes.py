"""
Masri Digital Compliance Platform — WISP API Routes

Provides WISP endpoints for the wizard frontend and document management:
  - POST /api/v1/wisp/assist          — LLM-assisted content generation for a step
  - POST /api/v1/wisp/generate         — Generate final WISP document from wizard data
  - POST /api/v1/wisp/<id>/export/pdf  — Export branded PDF
  - POST /api/v1/wisp/<id>/export/docx — Export branded DOCX
  - POST /api/v1/wisp/<id>/sign        — Digital signature capture
  - GET  /api/v1/wisp/<id>/versions    — Version history
  - POST /api/v1/wisp/<id>/llm-generate — LLM-generate all section text

Blueprint: ``wisp_bp`` at url_prefix ``/api/v1/wisp``
"""

import json
import logging
import os
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request, abort, current_app, send_file
from flask_login import current_user
from app.utils.decorators import login_required
from app import limiter
from app.masri.schemas import (
    validate_payload,
    WISPAssistSchema,
    WISPGenerateSchema,
    WISPSignSchema,
    WISPLLMGenerateSchema,
)

logger = logging.getLogger(__name__)

wisp_bp = Blueprint("wisp_bp", __name__, url_prefix="/api/v1/wisp")


@wisp_bp.route("/assist", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def wisp_assist():
    """
    POST /api/v1/wisp/assist

    Request body:
        {
            "step": <int>,
            "step_name": <str>,
            "data": { ... current step form data ... },
            "tenant_id": <str, optional>
        }

    Returns LLM-generated draft content for the given wizard step.
    """
    if not current_app.config.get("LLM_ENABLED"):
        return jsonify({"error": "LLM features are not enabled"}), 403

    data, err = validate_payload(WISPAssistSchema, request.get_json(silent=True))
    if err:
        return err

    step = data.get("step")
    step_name = data.get("step_name", "")
    step_data = data.get("data", {})
    tenant_id = data.get("tenant_id")

    try:
        from app.masri.llm_service import LLMService

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compliance assistant helping draft a Written "
                    "Information Security Program (WISP). Generate professional, "
                    "compliance-ready language suitable for a WISP document."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Generate content for the section: '{step_name}'.\n\n"
                    f"Context data:\n{_format_step_data(step_data)}"
                ),
            },
        ]

        result = LLMService.chat(
            messages=messages,
            tenant_id=tenant_id,
            max_tokens=1500,
        )

        return jsonify({
            "content": result.get("content", ""),
            "tokens_used": result.get("usage", {}).get("total_tokens", 0),
        })
    except Exception as e:
        logger.exception("WISP assist failed for step %s", step)
        return jsonify({"error": "Failed to generate WISP content"}), 500


@wisp_bp.route("/generate", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def wisp_generate():
    """
    POST /api/v1/wisp/generate

    Request body:
        {
            "wizard_data": { ... all 10 steps of wizard data ... },
            "tenant_id": <str>,
            "format": "html" | "pdf"  (optional, default "html")
        }

    Generates and persists the final WISP document.
    """
    data, err = validate_payload(WISPGenerateSchema, request.get_json(silent=True))
    if err:
        return err

    wizard_data = data.get("wizard_data", {})
    tenant_id = data.get("tenant_id")
    output_format = data.get("format", "html")

    try:
        from app.masri.new_models import WISPDocument, WISPVersion
        from app import db

        # Create or update WISP document record
        wisp_doc = db.session.execute(db.select(WISPDocument).filter_by(tenant_id=tenant_id)).scalars().first()
        if not wisp_doc:
            wisp_doc = WISPDocument(
                tenant_id=tenant_id,
                status="draft",
                firm_name=wizard_data.get("firm_name", ""),
            )
            db.session.add(wisp_doc)
            db.session.flush()

        # Create a new version
        new_version = (wisp_doc.version or 0) + 1
        version = WISPVersion(
            wisp_id=wisp_doc.id,
            version=new_version,
            snapshot_json=json.dumps(wizard_data),
            created_by_user_id=current_user.id,
            change_summary="Generated from wizard",
        )
        wisp_doc.version = new_version
        wisp_doc.date_updated = datetime.utcnow()

        db.session.add(version)
        db.session.commit()

        return jsonify({
            "id": wisp_doc.id,
            "version": version.version,
            "status": wisp_doc.status,
            "message": "WISP document generated successfully",
        }), 201
    except Exception as e:
        logger.exception("WISP document generation failed")
        from app import db
        db.session.rollback()
        return jsonify({"error": "Failed to generate WISP document"}), 500


# ---------------------------------------------------------------------------
# Phase 5 new endpoints
# ---------------------------------------------------------------------------

def _build_branding() -> dict:
    """Build branding dict from app config for export use."""
    return {
        "app_name": current_app.config.get("APP_NAME", "Masri Digital"),
        "logo_url": current_app.config.get("APP_LOGO_URL", "/static/img/logo.svg"),
        "primary_color": current_app.config.get("APP_PRIMARY_COLOR", "#0066CC"),
        "support_email": current_app.config.get("SUPPORT_EMAIL", "support@masridigital.com"),
    }


@wisp_bp.route("/<wisp_id>/export/pdf", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def wisp_export_pdf(wisp_id):
    """Export WISP document as branded PDF."""
    from app.masri.new_models import WISPDocument
    from app.masri.wisp_export import WISPExporter
    from app import db

    wisp = db.get_or_404(WISPDocument, wisp_id)
    # Enforce tenant ownership — any authenticated user who knows the ID should not
    # be able to access another tenant's WISP document
    if wisp.tenant_id != current_user.tenant_id and not current_user.super:
        from flask import abort as _abort
        _abort(403, "Access denied")
    branding = _build_branding()

    export_dir = os.path.join(current_app.instance_path, "exports")
    os.makedirs(export_dir, exist_ok=True)
    filename = f"wisp_{secrets.token_hex(16)}.pdf"
    output_path = os.path.join(export_dir, filename)

    exporter = WISPExporter(wisp, branding)
    result_path = exporter.export_pdf(output_path)

    # Store path on the document
    from app import db
    wisp.pdf_path = result_path
    db.session.commit()

    return send_file(
        result_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"WISP_{wisp.firm_name or 'document'}.pdf",
    )


@wisp_bp.route("/<wisp_id>/export/docx", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def wisp_export_docx(wisp_id):
    """Export WISP document as branded DOCX."""
    from app.masri.new_models import WISPDocument
    from app.masri.wisp_export import WISPExporter
    from app import db

    wisp = db.get_or_404(WISPDocument, wisp_id)
    # Enforce tenant ownership — any authenticated user who knows the ID should not
    # be able to access another tenant's WISP document
    if wisp.tenant_id != current_user.tenant_id and not current_user.super:
        from flask import abort as _abort
        _abort(403, "Access denied")
    branding = _build_branding()

    export_dir = os.path.join(current_app.instance_path, "exports")
    os.makedirs(export_dir, exist_ok=True)
    filename = f"wisp_{secrets.token_hex(16)}.docx"
    output_path = os.path.join(export_dir, filename)

    exporter = WISPExporter(wisp, branding)
    result_path = exporter.export_docx(output_path)

    from app import db
    wisp.docx_path = result_path
    db.session.commit()

    return send_file(
        result_path,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"WISP_{wisp.firm_name or 'document'}.docx",
    )


@wisp_bp.route("/<wisp_id>/sign", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def wisp_sign(wisp_id):
    """
    POST /api/v1/wisp/<wisp_id>/sign

    Request body:
        { "signature_data": "<base64 signature image or text>" }

    Records the current user as having signed the WISP.
    """
    from app.masri.new_models import WISPDocument
    from app import db

    wisp = db.get_or_404(WISPDocument, wisp_id)
    # Enforce tenant ownership — any authenticated user who knows the ID should not
    # be able to access another tenant's WISP document
    if wisp.tenant_id != current_user.tenant_id and not current_user.super:
        from flask import abort as _abort
        _abort(403, "Access denied")

    data, err = validate_payload(WISPSignSchema, request.get_json(silent=True))
    if err:
        return err
    signature_data = data.get("signature_data")

    wisp.signed_by_user_id = current_user.id
    wisp.signed_at = datetime.utcnow()
    wisp.status = "signed"
    db.session.commit()

    logger.info("WISP %s signed by user %s", wisp_id, current_user.id)

    return jsonify({
        "id": wisp.id,
        "status": wisp.status,
        "signed_by": wisp.signed_by_user_id,
        "signed_at": wisp.signed_at.isoformat(),
        "message": "WISP document signed successfully",
    })


@wisp_bp.route("/<wisp_id>/versions", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def wisp_versions(wisp_id):
    """
    GET /api/v1/wisp/<wisp_id>/versions

    Returns version history for a WISP document.
    """
    from app.masri.new_models import WISPDocument, WISPVersion
    from app import db

    wisp = db.get_or_404(WISPDocument, wisp_id)
    # Enforce tenant ownership — any authenticated user who knows the ID should not
    # be able to access another tenant's WISP document
    if wisp.tenant_id != current_user.tenant_id and not current_user.super:
        from flask import abort as _abort
        _abort(403, "Access denied")

    versions = (
        db.session.execute(
            db.select(WISPVersion)
            .filter_by(wisp_id=wisp_id)
            .order_by(WISPVersion.version.desc())
        ).scalars().all()
    )

    return jsonify({
        "wisp_id": wisp_id,
        "current_version": wisp.version,
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "change_summary": v.change_summary,
                "created_by_user_id": v.created_by_user_id,
                "date_added": v.date_added.isoformat() if v.date_added else None,
            }
            for v in versions
        ],
    })


@wisp_bp.route("/<wisp_id>/llm-generate", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def wisp_llm_generate(wisp_id):
    """
    POST /api/v1/wisp/<wisp_id>/llm-generate

    Request body (optional):
        { "sections": ["firm_profile", "risk_assessment", ...] }

    Uses LLM to generate polished text for all (or specified) WISP sections
    and stores the result in ``generated_text_json``.
    """
    if not current_app.config.get("LLM_ENABLED"):
        return jsonify({"error": "LLM features are not enabled"}), 403

    from app.masri.new_models import WISPDocument
    from app.masri.llm_service import LLMService
    from app.masri.wisp_export import SECTIONS
    from app import db

    wisp = db.get_or_404(WISPDocument, wisp_id)
    # Enforce tenant ownership — any authenticated user who knows the ID should not
    # be able to access another tenant's WISP document
    if wisp.tenant_id != current_user.tenant_id and not current_user.super:
        from flask import abort as _abort
        _abort(403, "Access denied")

    data, err = validate_payload(WISPLLMGenerateSchema, request.get_json(silent=True))
    if err:
        return err
    requested_sections = data.get("sections")

    # Determine which sections to generate
    section_keys = [s[0] for s in SECTIONS]
    if requested_sections:
        section_keys = [k for k in section_keys if k in requested_sections]

    # Build context from raw wizard data
    from app.masri.wisp_export import WISPExporter
    exporter = WISPExporter(wisp, {})

    generated = {}
    if isinstance(wisp.generated_text_json, dict):
        generated = dict(wisp.generated_text_json)
    elif isinstance(wisp.generated_text_json, str):
        try:
            generated = json.loads(wisp.generated_text_json)
        except (json.JSONDecodeError, TypeError):
            generated = {}

    tenant_id = wisp.tenant_id
    errors = []

    for section_key in section_keys:
        section_title = next(
            (t for k, t in SECTIONS if k == section_key), section_key
        )
        raw_content = exporter._get_section_content(section_key)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compliance document writer. Rewrite the following "
                    "raw data into polished, professional WISP section text. "
                    "Use clear paragraphs, no markdown formatting."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Section: {section_title}\n\nRaw data:\n{raw_content}"
                ),
            },
        ]

        try:
            result = LLMService.chat(
                messages=messages,
                tenant_id=tenant_id,
                temperature=0.3,
                max_tokens=1500,
            )
            generated[section_key] = result["content"]
        except Exception as e:
            logger.warning("LLM generation failed for section %s: %s", section_key, e)
            errors.append(section_key)

    wisp.generated_text_json = json.dumps(generated)
    db.session.commit()

    return jsonify({
        "wisp_id": wisp_id,
        "sections_generated": [k for k in section_keys if k not in errors],
        "errors": errors,
        "message": "LLM generation complete",
    })


def _format_step_data(data: dict) -> str:
    """Format step data dict into a readable prompt string."""
    lines = []
    for key, value in data.items():
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    return "\n".join(lines) if lines else "(No data provided)"
