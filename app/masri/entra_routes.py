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
from app import limiter

logger = logging.getLogger(__name__)


def _require_platform_admin():
    """Abort 403 if the current user is not a platform superuser."""
    Authorizer(current_user).can_user_manage_platform()

entra_bp = Blueprint("entra_bp", __name__, url_prefix="/api/v1/entra")


def _get_entra_client():
    """
    Build an EntraIntegration instance.

    Credential resolution order:
      1. SettingsEntra DB record (Fernet-encrypted, preferred)
      2. ENTRA_* environment variables / app.config (legacy fallback)

    Raises RuntimeError if no credentials are found in either source.
    """
    from app.masri.entra_integration import EntraIntegration
    from app.masri.settings_service import SettingsService

    creds = SettingsService.get_entra_config()

    # Fall back to env vars if the DB record is absent or incomplete
    if not creds or not all(creds.values()):
        tenant_id = current_app.config.get("ENTRA_TENANT_ID")
        client_id = current_app.config.get("ENTRA_CLIENT_ID")
        client_secret = current_app.config.get("ENTRA_CLIENT_SECRET")

        if not all([tenant_id, client_id, client_secret]):
            raise RuntimeError(
                "Microsoft Entra ID is not configured. "
                "Contact your platform administrator."
            )

        creds = {
            "entra_tenant_id": tenant_id,
            "client_id": client_id,
            "client_secret": client_secret,
        }

    return EntraIntegration(
        tenant_id=creds["entra_tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )


@entra_bp.route("/test", methods=["POST"])
@limiter.limit("30 per minute")
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
@limiter.limit("60 per minute")
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
@limiter.limit("60 per minute")
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


@entra_bp.route("/csp-clients", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def entra_csp_clients():
    """
    GET /api/v1/entra/csp-clients

    Lists CSP/partner managed tenants from Microsoft Graph.
    Returns clients with their tenant IDs and names.
    """
    _require_platform_admin()
    try:
        client = _get_entra_client()
        csp_clients = client.list_csp_clients()
        return jsonify({"clients": csp_clients, "count": len(csp_clients)})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("CSP client list failed")
        return jsonify({"error": str(e)}), 500


@entra_bp.route("/csp-clients/import", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def entra_import_csp_clients():
    """
    POST /api/v1/entra/csp-clients/import

    Import selected CSP clients as tenants. Maps to existing tenants by name
    before creating new ones.

    Body: { "clients": [{ "customer_tenant_id": "...", "display_name": "...", "domain": "..." }] }
    """
    _require_platform_admin()
    from app.models import Tenant, db
    from app.models import Logs

    data = request.get_json(silent=True) or {}
    clients_to_import = data.get("clients", [])
    if not clients_to_import:
        return jsonify({"error": "No clients provided"}), 400

    results = {"mapped": 0, "created": 0, "skipped": 0, "details": []}

    for csp in clients_to_import:
        name = csp.get("display_name", "").strip()
        if not name:
            results["skipped"] += 1
            continue

        # Try to map to existing tenant by name (case-insensitive)
        from sqlalchemy import func
        existing = db.session.execute(
            db.select(Tenant).filter(func.lower(Tenant.name) == func.lower(name))
        ).scalars().first()

        if existing:
            results["mapped"] += 1
            results["details"].append({
                "name": name, "action": "mapped", "tenant_id": existing.id,
                "message": f"Mapped to existing tenant: {existing.name}"
            })
        else:
            # Create new tenant
            try:
                tenant = Tenant.create(
                    current_user, name,
                    email=csp.get("domain", ""),
                    init_data=True,
                )
                results["created"] += 1
                results["details"].append({
                    "name": name, "action": "created", "tenant_id": tenant.id,
                    "message": f"Created new tenant: {name}"
                })
                Logs.add(
                    message=f"CSP client imported: {name}",
                    action="POST", namespace="entra",
                    user_id=current_user.id,
                )
            except Exception as e:
                results["skipped"] += 1
                results["details"].append({
                    "name": name, "action": "error",
                    "message": f"Failed: {str(e)}"
                })

    return jsonify(results)


@entra_bp.route("/assess", methods=["POST"])
@limiter.limit("5 per minute")
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
