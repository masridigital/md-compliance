"""
Masri Digital Compliance Platform — DefensX API Routes

Exposes DefensX endpoints:
  - POST /api/v1/defensx/test       — Test API connection
  - GET  /api/v1/defensx/customers  — List managed customers

Blueprint: ``defensx_bp`` at url_prefix ``/api/v1/defensx``

NOTE: DefensX does not publish a public API reference. Endpoint paths
are based on the integration specification and may need adjustment once
API access is confirmed with DefensX partner support.
"""

import logging

from flask import Blueprint, jsonify
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import limiter

logger = logging.getLogger(__name__)

defensx_bp = Blueprint("defensx_bp", __name__, url_prefix="/api/v1/defensx")


def _require_admin():
    """Abort 403 if the current user is not a platform admin."""
    Authorizer(current_user).can_user_manage_platform()


def _get_defensx_client():
    """
    Build a DefensXIntegration instance from encrypted DB credentials
    or fall back to env vars.
    """
    from flask import current_app
    from app.masri.defensx_integration import DefensXIntegration

    api_token = None

    # Try DB-stored config first
    try:
        from app import db
        result = db.session.execute(
            db.text("SELECT config_enc FROM settings_storage WHERE provider = 'defensx' LIMIT 1")
        ).scalar()
        if result:
            from app.masri.settings_service import decrypt_value
            import json
            config = json.loads(decrypt_value(result))
            api_token = config.get("api_token")
    except Exception:
        pass

    # Fall back to env var
    if not api_token:
        api_token = current_app.config.get("DEFENSX_API_TOKEN")

    if not api_token:
        raise RuntimeError(
            "DefensX is not configured. Add your API token in Integrations."
        )

    return DefensXIntegration(api_token)


# ─── Test Connection ──────────────────────────────────────────────

@defensx_bp.route("/test", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def defensx_test():
    """POST /api/v1/defensx/test — Test API connection."""
    try:
        client = _get_defensx_client()
        result = client.test_connection()
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"connected": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("DefensX connection test failed")
        return jsonify({"connected": False, "error": "Connection test failed"}), 500


# ─── Customers ────────────────────────────────────────────────────

@defensx_bp.route("/customers", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def defensx_customers():
    """GET /api/v1/defensx/customers — List all managed customers."""
    _require_admin()
    try:
        client = _get_defensx_client()
        customers = client.list_customers()
        return jsonify(customers)
    except RuntimeError as e:
        logger.warning("DefensX API error: %s", e)
        return jsonify({"error": "Integration request failed. Check credentials and try again."}), 400
    except Exception:
        logger.exception("DefensX customer list failed")
        return jsonify({"error": "An internal error occurred"}), 500
