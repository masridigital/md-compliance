"""
Masri Digital Compliance Platform — Entra ID API Routes

Exposes Microsoft Entra ID (Azure AD) integration endpoints:
  - POST /api/v1/entra/test     — Test Graph API connection
  - GET  /api/v1/entra/users    — List directory users
  - GET  /api/v1/entra/mfa-status — MFA registration status
  - POST /api/v1/entra/assess   — Compliance posture assessment

Blueprint: ``entra_bp`` at url_prefix ``/api/v1/entra``
"""

import logging

from flask import Blueprint, jsonify, request, current_app, abort
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer

logger = logging.getLogger(__name__)


def _require_platform_admin():
    """Abort 403 if the current user is not a platform superuser."""
    Authorizer(current_user).can_user_manage_platform()

entra_bp = Blueprint("entra_bp", __name__, url_prefix="/api/v1/entra")


def _get_entra_client():
    """
    Build an EntraIntegration instance from app config.

    Raises RuntimeError if Entra ID is not configured.
    """
    from app.masri.entra_integration import EntraIntegration

    tenant_id = current_app.config.get("ENTRA_TENANT_ID")
    client_id = current_app.config.get("ENTRA_CLIENT_ID")
    client_secret = current_app.config.get("ENTRA_CLIENT_SECRET")

    if not all([tenant_id, client_id, client_secret]):
        raise RuntimeError(
            "Entra ID not configured. Set ENTRA_TENANT_ID, "
            "ENTRA_CLIENT_ID, and ENTRA_CLIENT_SECRET."
        )

    return EntraIntegration(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


@entra_bp.route("/test", methods=["POST"])
@login_required
def entra_test():
    """
    POST /api/v1/entra/test

    Tests the Microsoft Graph API connection. Requires platform admin.
    """
    _require_platform_admin()
    try:
        client = _get_entra_client()
        result = client.test_connection()
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"connected": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Entra connection test failed")
        return jsonify({"connected": False, "error": str(e)}), 500


@entra_bp.route("/users", methods=["GET"])
@login_required
def entra_users():
    """
    GET /api/v1/entra/users?limit=100

    Lists users from the Azure AD directory. Requires platform admin.
    """
    _require_platform_admin()
    limit = request.args.get("limit", 100, type=int)

    try:
        client = _get_entra_client()
        users = client.list_users(limit=limit)
        return jsonify({"users": users, "count": len(users)})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Entra user listing failed")
        return jsonify({"error": str(e)}), 500


@entra_bp.route("/mfa-status", methods=["GET"])
@login_required
def entra_mfa_status():
    """
    GET /api/v1/entra/mfa-status

    Returns MFA registration status for all directory users. Requires platform admin.
    """
    _require_platform_admin()
    try:
        client = _get_entra_client()
        mfa_data = client.get_mfa_status()

        total = len(mfa_data)
        registered = sum(1 for u in mfa_data if u.get("mfa_registered"))

        return jsonify({
            "users": mfa_data,
            "summary": {
                "total_users": total,
                "mfa_registered": registered,
                "mfa_rate": round(registered / total * 100, 1) if total > 0 else 0,
            },
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Entra MFA status check failed")
        return jsonify({"error": str(e)}), 500


@entra_bp.route("/assess", methods=["POST"])
@login_required
def entra_assess():
    """
    POST /api/v1/entra/assess

    Performs a compliance posture assessment based on Entra ID
    configuration. Requires platform admin.
    """
    _require_platform_admin()
    try:
        client = _get_entra_client()
        assessment = client.assess_compliance()
        return jsonify({"assessment": assessment})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Entra compliance assessment failed")
        return jsonify({"error": str(e)}), 500
