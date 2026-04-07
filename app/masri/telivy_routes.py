"""
Masri Digital Compliance Platform — Telivy API Routes

Exposes Telivy Security endpoints:
  - POST /api/v1/telivy/test                — Test API connection
  - GET  /api/v1/telivy/external-scans      — List external scans
  - POST /api/v1/telivy/external-scans      — Create external scan
  - GET  /api/v1/telivy/external-scans/:id  — Get scan details
  - GET  /api/v1/telivy/external-scans/:id/findings — Get findings
  - GET  /api/v1/telivy/external-scans/:id/breach-data — Get breach data
  - GET  /api/v1/telivy/external-scans/:id/report — Download report
  - GET  /api/v1/telivy/risk-assessments    — List risk assessments
  - POST /api/v1/telivy/risk-assessments    — Create risk assessment
  - GET  /api/v1/telivy/risk-assessments/:id — Get assessment details
  - GET  /api/v1/telivy/risk-assessments/:id/devices — Get devices
  - GET  /api/v1/telivy/risk-assessments/:id/scan-status — Scan status
  - GET  /api/v1/telivy/risk-assessments/:id/report — Download report

Blueprint: ``telivy_bp`` at url_prefix ``/api/v1/telivy``
"""

import logging

from flask import Blueprint, jsonify, request, send_file, abort
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import limiter

logger = logging.getLogger(__name__)

telivy_bp = Blueprint("telivy_bp", __name__, url_prefix="/api/v1/telivy")


def _require_admin():
    """Abort 403 if the current user is not a platform admin."""
    Authorizer(current_user).can_user_manage_platform()


def _get_telivy_client():
    """
    Build a TelivyIntegration instance from encrypted DB credentials
    or fall back to env vars.
    """
    from flask import current_app
    from app.masri.telivy_integration import TelivyIntegration
    from app.masri.settings_service import SettingsService

    # Try DB-stored config first
    try:
        ps = SettingsService.get_platform_settings()
        api_key = getattr(ps, "telivy_api_key", None)
    except Exception:
        api_key = None

    # Fall back to stored encrypted value via custom query
    if not api_key:
        from app import db
        try:
            result = db.session.execute(
                db.text("SELECT config_enc FROM settings_storage WHERE provider = 'telivy' LIMIT 1")
            ).scalar()
            if result:
                from app.masri.settings_service import decrypt_value
                import json
                config = json.loads(decrypt_value(result))
                api_key = config.get("api_key")
        except Exception:
            pass

    # Fall back to env var
    if not api_key:
        api_key = current_app.config.get("TELIVY_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Telivy is not configured. Add your API key in Integrations."
        )

    return TelivyIntegration(api_key)


# ─── Test Connection ──────────────────────────────────────────────

@telivy_bp.route("/test", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def telivy_test():
    """POST /api/v1/telivy/test — Test API connection."""
    try:
        client = _get_telivy_client()
        result = client.test_connection()
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"connected": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Telivy connection test failed")
        return jsonify({"connected": False, "error": str(e)}), 500


# ─── External Scans ──────────────────────────────────────────────

@telivy_bp.route("/external-scans", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_external_scans():
    """GET /api/v1/telivy/external-scans"""
    try:
        client = _get_telivy_client()
        result = client.list_external_scans(
            search=request.args.get("search"),
            limit=request.args.get("limit", 100, type=int),
            offset=request.args.get("offset", 0, type=int),
        )
        return jsonify(result)
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy list external scans failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/external-scans", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_external_scan():
    """POST /api/v1/telivy/external-scans"""
    data = request.get_json() or {}
    org_name = data.get("organizationName")
    domain = data.get("domain")
    if not org_name or not domain:
        return jsonify({"error": "organizationName and domain are required"}), 400
    try:
        client = _get_telivy_client()
        result = client.create_external_scan(
            org_name, domain,
            client_category=data.get("clientCategory"),
            client_status=data.get("clientStatus"),
        )
        return jsonify(result), 201
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy create external scan failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/external-scans/<string:scan_id>", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_external_scan(scan_id):
    """GET /api/v1/telivy/external-scans/:id"""
    try:
        client = _get_telivy_client()
        return jsonify(client.get_external_scan(scan_id))
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy get external scan failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/external-scans/<string:scan_id>/findings", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_external_scan_findings(scan_id):
    """GET /api/v1/telivy/external-scans/:id/findings"""
    try:
        client = _get_telivy_client()
        return jsonify(client.get_external_scan_findings(scan_id))
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy get findings failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/external-scans/<string:scan_id>/breach-data", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_breach_data(scan_id):
    """GET /api/v1/telivy/external-scans/:id/breach-data"""
    try:
        client = _get_telivy_client()
        return jsonify(client.get_breach_data(scan_id))
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy get breach data failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/external-scans/<string:scan_id>/report", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def download_external_scan_report(scan_id):
    """GET /api/v1/telivy/external-scans/:id/report"""
    import io
    fmt = request.args.get("format", "pdf")
    detailed = request.args.get("detailed", "false").lower() == "true"
    inline = request.args.get("inline", "false").lower() == "true"
    try:
        client = _get_telivy_client()
        content = client.download_external_scan_report(scan_id, detailed=detailed, fmt=fmt)
        mime = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return send_file(io.BytesIO(content), mimetype=mime,
                         as_attachment=not inline,
                         download_name=f"telivy-scan-{scan_id}.{fmt}")
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy download report failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


# ─── Risk Assessments ─────────────────────────────────────────────

@telivy_bp.route("/risk-assessments", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_risk_assessments():
    """GET /api/v1/telivy/risk-assessments"""
    try:
        client = _get_telivy_client()
        result = client.list_risk_assessments(
            search=request.args.get("search"),
            limit=request.args.get("limit", 100, type=int),
            offset=request.args.get("offset", 0, type=int),
        )
        return jsonify(result)
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy list risk assessments failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/risk-assessments", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_risk_assessment():
    """POST /api/v1/telivy/risk-assessments"""
    data = request.get_json() or {}
    org_name = data.get("organizationName")
    domain = data.get("domain")
    if not org_name or not domain:
        return jsonify({"error": "organizationName and domain are required"}), 400
    try:
        client = _get_telivy_client()
        result = client.create_risk_assessment(
            org_name, domain,
            country=data.get("country", "US"),
            is_light_scan=data.get("isLightScan", True),
            client_category=data.get("clientCategory"),
            client_status=data.get("clientStatus"),
        )
        return jsonify(result), 201
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy create risk assessment failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/risk-assessments/<string:assessment_id>", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_risk_assessment(assessment_id):
    """GET /api/v1/telivy/risk-assessments/:id"""
    try:
        client = _get_telivy_client()
        return jsonify(client.get_risk_assessment(assessment_id))
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy get risk assessment failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/risk-assessments/<string:assessment_id>/devices", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_risk_assessment_devices(assessment_id):
    """GET /api/v1/telivy/risk-assessments/:id/devices"""
    try:
        client = _get_telivy_client()
        return jsonify(client.get_risk_assessment_devices(assessment_id))
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy get devices failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/risk-assessments/<string:assessment_id>/scan-status", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_scan_status(assessment_id):
    """GET /api/v1/telivy/risk-assessments/:id/scan-status"""
    try:
        client = _get_telivy_client()
        return jsonify(client.get_scan_status(assessment_id))
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy get scan status failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500


@telivy_bp.route("/risk-assessments/<string:assessment_id>/report", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def download_risk_assessment_report(assessment_id):
    """GET /api/v1/telivy/risk-assessments/:id/report"""
    import io
    report_type = request.args.get("reportType", "telivy_complete_report_pdf")
    inline = request.args.get("inline", "false").lower() == "true"
    try:
        client = _get_telivy_client()
        content = client.download_risk_assessment_report(assessment_id, report_type=report_type)
        ext = "pdf" if "pdf" in report_type else "docx"
        mime = "application/pdf" if ext == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return send_file(io.BytesIO(content), mimetype=mime,
                         as_attachment=not inline,
                         download_name=f"telivy-assessment-{assessment_id}.{ext}")
    except RuntimeError as e:
        logger.warning("Telivy API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception as e:
        logger.exception("Telivy download report failed")
        return jsonify({"error": "An internal error occurred. Check system logs for details."}), 500
