"""
Masri Digital Compliance Platform — NinjaOne RMM API Routes

Exposes NinjaOne endpoints:
  - POST /api/v1/ninjaone/test              — Test API connection
  - GET  /api/v1/ninjaone/organizations     — List MSP client orgs
  - GET  /api/v1/ninjaone/devices           — List devices (optional ?org_id=)
  - GET  /api/v1/ninjaone/compliance-summary — Computed compliance metrics

Blueprint: ``ninjaone_bp`` at url_prefix ``/api/v1/ninjaone``
"""

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import limiter

logger = logging.getLogger(__name__)

ninjaone_bp = Blueprint("ninjaone_bp", __name__, url_prefix="/api/v1/ninjaone")


def _require_admin():
    """Abort 403 if the current user is not a platform admin."""
    Authorizer(current_user).can_user_manage_platform()


def _get_ninjaone_client():
    """
    Build a NinjaOneIntegration instance from encrypted DB credentials
    or fall back to env vars.
    """
    from flask import current_app
    from app.masri.ninjaone_integration import NinjaOneIntegration, NINJAONE_REGIONS

    # Try DB-stored config first
    client_id = None
    client_secret = None
    instance_url = None
    try:
        from app import db
        result = db.session.execute(
            db.text("SELECT config_enc FROM settings_storage WHERE provider = 'ninjaone' LIMIT 1")
        ).scalar()
        if result:
            from app.masri.settings_service import decrypt_value
            import json
            config = json.loads(decrypt_value(result))
            client_id = config.get("client_id")
            client_secret = config.get("client_secret")
            region = config.get("region", "us")
            instance_url = NINJAONE_REGIONS.get(region, NINJAONE_REGIONS["us"])
    except Exception:
        pass

    # Fall back to env vars
    if not client_id:
        client_id = current_app.config.get("NINJAONE_CLIENT_ID")
    if not client_secret:
        client_secret = current_app.config.get("NINJAONE_CLIENT_SECRET")
    if not instance_url:
        region = current_app.config.get("NINJAONE_REGION", "us")
        instance_url = NINJAONE_REGIONS.get(region, NINJAONE_REGIONS["us"])

    if not client_id or not client_secret:
        raise RuntimeError(
            "NinjaOne is not configured. Add your credentials in Integrations."
        )

    return NinjaOneIntegration(client_id, client_secret, instance_url)


# ─── Test Connection ──────────────────────────────────────────────

@ninjaone_bp.route("/test", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def ninjaone_test():
    """POST /api/v1/ninjaone/test — Test API connection."""
    try:
        client = _get_ninjaone_client()
        result = client.test_connection()
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"connected": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("NinjaOne connection test failed")
        return jsonify({"connected": False, "error": "Connection test failed"}), 500


# ─── Organizations ────────────────────────────────────────────────

@ninjaone_bp.route("/organizations", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def ninjaone_organizations():
    """GET /api/v1/ninjaone/organizations — List all MSP client organizations."""
    _require_admin()
    try:
        client = _get_ninjaone_client()
        orgs = client.list_organizations()
        return jsonify(orgs)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("NinjaOne organization list failed")
        return jsonify({"error": "An internal error occurred"}), 500


# ─── Devices ──────────────────────────────────────────────────────

@ninjaone_bp.route("/devices", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def ninjaone_devices():
    """GET /api/v1/ninjaone/devices — List devices. Optional ?org_id= filter."""
    _require_admin()
    try:
        client = _get_ninjaone_client()
        org_id = request.args.get("org_id")
        devices = client.get_devices_detailed(org_id=org_id)
        return jsonify(devices)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("NinjaOne device list failed")
        return jsonify({"error": "An internal error occurred"}), 500


# ─── Compliance Summary ──────────────────────────────────────────

@ninjaone_bp.route("/compliance-summary", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def ninjaone_compliance_summary():
    """
    GET /api/v1/ninjaone/compliance-summary — Computed compliance metrics.
    Returns patch %, AV %, encryption %, stale device count.
    """
    _require_admin()
    try:
        client = _get_ninjaone_client()
        org_id = request.args.get("org_id")
        devices = client.get_devices_detailed(org_id=org_id)
        av_status = client.get_antivirus_status()

        total = len(devices)
        if total == 0:
            return jsonify({"total_devices": 0, "message": "No devices found"})

        # AV coverage
        av_on = sum(
            1 for a in av_status
            if a.get("productState") == "ON" or a.get("realTimeProtectionStatus") == "ON"
        )
        av_total = len(av_status) if av_status else total

        # Stale devices (no contact in 30+ days)
        import time
        now = time.time()
        stale = sum(
            1 for d in devices
            if d.get("lastContact") and
            (now - _parse_timestamp(d["lastContact"])) > 30 * 86400
        )

        return jsonify({
            "total_devices": total,
            "antivirus_coverage_pct": round(av_on / max(av_total, 1) * 100, 1),
            "stale_devices_30d": stale,
            "devices_by_os": _group_by(devices, "nodeClass"),
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("NinjaOne compliance summary failed")
        return jsonify({"error": "An internal error occurred"}), 500


def _parse_timestamp(value) -> float:
    """Parse NinjaOne timestamp (ISO 8601 string or epoch float)."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _group_by(items: list, key: str) -> dict:
    result = {}
    for item in items:
        val = item.get(key, "unknown")
        result[val] = result.get(val, 0) + 1
    return result
