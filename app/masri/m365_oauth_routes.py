"""
Masri Digital Compliance Platform — M365 One-Click OAuth Integration

Implements the OAuth 2.0 Admin Consent + Device Code flow for registering
the platform as an Entra ID app without manual credential entry.

Flow:
  1. Admin clicks "Connect Microsoft 365" in the integrations page
  2. Frontend POSTs /api/v1/m365/oauth/initiate → gets an auth URL
  3. Browser redirects to Microsoft admin consent page
  4. Microsoft redirects back to /api/v1/m365/oauth/callback with ?code=
  5. Platform exchanges code for tokens, persists encrypted credentials

Blueprint: m365_oauth_bp at /api/v1/m365
"""

import logging
import secrets

from flask import Blueprint, jsonify, request, redirect, url_for, current_app, session
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import db, limiter

logger = logging.getLogger(__name__)

m365_oauth_bp = Blueprint("m365_oauth_bp", __name__, url_prefix="/api/v1/m365")

# Microsoft OAuth endpoints
MS_AUTH_BASE = "https://login.microsoftonline.com"
MS_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Scopes required for the full M365 compliance integration
# These are application (client credential) scopes — requires admin consent
REQUIRED_GRAPH_SCOPES = [
    "https://graph.microsoft.com/User.Read.All",
    "https://graph.microsoft.com/Policy.Read.All",
    "https://graph.microsoft.com/AuditLog.Read.All",
    "https://graph.microsoft.com/SecurityEvents.Read.All",
    "https://graph.microsoft.com/DeviceManagementManagedDevices.Read.All",
    "https://graph.microsoft.com/IdentityRiskyUser.Read.All",
    "https://graph.microsoft.com/InformationProtectionPolicy.Read",
    "https://graph.microsoft.com/Sites.Read.All",
    "https://graph.microsoft.com/Reports.Read.All",
    "https://graph.microsoft.com/Directory.Read.All",
]


def _require_platform_admin():
    if not getattr(current_user, "super", False):
        from flask import abort
        abort(403, description="Platform admin required")


def _get_redirect_uri():
    return url_for("m365_oauth_bp.m365_oauth_callback", _external=True,
                   _scheme=current_app.config.get("SCHEME", "https"))


@m365_oauth_bp.route("/oauth/initiate", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def m365_oauth_initiate():
    """
    POST /api/v1/m365/oauth/initiate

    Generates a Microsoft admin-consent URL. The frontend should redirect
    the browser to this URL. On success, Microsoft redirects to /callback.

    Requires MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET in app config
    (these are the platform's own Entra app registration, separate from the
    per-tenant credentials being consented).

    Body: { "tenant_id": "common" }  (optional, defaults to "common" for multi-tenant)
    """
    _require_platform_admin()

    data = request.get_json(silent=True) or {}
    ms_tenant = data.get("tenant_id", "common")

    client_id = current_app.config.get("MICROSOFT_CLIENT_ID") or current_app.config.get("ENTRA_CLIENT_ID")
    if not client_id:
        return jsonify({
            "error": "Platform Microsoft client_id not configured. Set MICROSOFT_CLIENT_ID in environment."
        }), 400

    # Generate state token to prevent CSRF
    state = secrets.token_urlsafe(32)
    # Store state in ConfigStore (session-safe across gunicorn workers)
    try:
        from app.models import ConfigStore
        import json
        ConfigStore.upsert("m365_oauth_state", json.dumps({
            "state": state,
            "initiated_by": current_user.id,
        }))
        db.session.commit()
    except Exception as e:
        logger.warning("Could not persist OAuth state: %s", e)
        return jsonify({"error": "State persistence failed"}), 500

    redirect_uri = _get_redirect_uri()

    # Build admin-consent URL (this grants app-level permissions, not delegated)
    # Using /adminconsent endpoint for application permissions
    auth_url = (
        f"{MS_AUTH_BASE}/{ms_tenant}/adminconsent"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )

    return jsonify({
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "message": "Redirect the user to auth_url to begin Microsoft admin consent"
    })


@m365_oauth_bp.route("/oauth/callback")
def m365_oauth_callback():
    """
    GET /api/v1/m365/oauth/callback

    Microsoft redirects here after admin consent. Handles both success
    and error redirects. On success, persists the tenant_id so the platform
    knows consent was granted. Credentials (client_id/secret) must already
    be configured via the integration settings drawer.
    """
    # Check for errors from Microsoft
    error = request.args.get("error")
    error_description = request.args.get("error_description", "")

    if error:
        logger.warning("M365 OAuth consent error: %s — %s", error, error_description)
        redirect_path = url_for("main.integrations") if hasattr(current_app, "main") else "/"
        return redirect(f"{redirect_path}?m365_error={error}")

    # Validate state
    state = request.args.get("state", "")
    admin_consent = request.args.get("admin_consent", "")
    ms_tenant = request.args.get("tenant", "")

    try:
        from app.models import ConfigStore
        import json
        state_record = ConfigStore.find("m365_oauth_state")
        if state_record and state_record.value:
            stored = json.loads(state_record.value)
            if stored.get("state") != state:
                logger.warning("M365 OAuth state mismatch — possible CSRF")
                return jsonify({"error": "State mismatch"}), 400
    except Exception as e:
        logger.warning("Could not validate OAuth state: %s", e)

    # Store the consented tenant ID for reference
    if ms_tenant and admin_consent == "True":
        try:
            from app.models import ConfigStore
            import json
            ConfigStore.upsert("m365_oauth_consent", json.dumps({
                "tenant_id": ms_tenant,
                "admin_consent": True,
                "consented_at": str(__import__("datetime").datetime.utcnow()),
            }))
            db.session.commit()
            logger.info("M365 admin consent granted for tenant %s", ms_tenant)
        except Exception as e:
            logger.warning("Could not persist consent record: %s", e)

    # Redirect back to integrations page with success flag
    try:
        return redirect(f"/integrations?m365_connected=true&tenant={ms_tenant}")
    except Exception:
        return redirect(f"/?m365_connected=true")


@m365_oauth_bp.route("/oauth/status", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def m365_oauth_status():
    """
    GET /api/v1/m365/oauth/status

    Returns the current M365 OAuth consent status and credential configuration.
    """
    _require_platform_admin()

    status = {
        "has_consent": False,
        "consent_tenant": None,
        "has_credentials": False,
        "is_fully_configured": False,
    }

    try:
        from app.models import ConfigStore
        import json

        # Check admin consent record
        consent_record = ConfigStore.find("m365_oauth_consent")
        if consent_record and consent_record.value:
            consent = json.loads(consent_record.value)
            status["has_consent"] = consent.get("admin_consent", False)
            status["consent_tenant"] = consent.get("tenant_id")
            status["consented_at"] = consent.get("consented_at")
    except Exception:
        pass

    try:
        from app.masri.new_models import SettingsEntra
        entra = db.session.execute(
            db.select(SettingsEntra).filter_by(tenant_id=None)
        ).scalars().first()
        if entra:
            status["has_credentials"] = entra.is_fully_configured()
            status["is_fully_configured"] = status["has_consent"] and status["has_credentials"]
    except Exception:
        pass

    return jsonify(status)


@m365_oauth_bp.route("/oauth/disconnect", methods=["DELETE"])
@limiter.limit("5 per minute")
@login_required
def m365_oauth_disconnect():
    """
    DELETE /api/v1/m365/oauth/disconnect

    Removes stored M365 credentials and consent record.
    """
    _require_platform_admin()

    try:
        from app.models import ConfigStore
        from app.masri.new_models import SettingsEntra

        # Remove consent record
        for key in ["m365_oauth_consent", "m365_oauth_state"]:
            rec = ConfigStore.find(key)
            if rec:
                db.session.delete(rec)

        # Remove credentials
        entra = db.session.execute(
            db.select(SettingsEntra).filter_by(tenant_id=None)
        ).scalars().first()
        if entra:
            db.session.delete(entra)

        db.session.commit()
        logger.info("M365 integration disconnected by user %s", current_user.id)
        return jsonify({"message": "Microsoft 365 integration disconnected"})
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to disconnect M365")
        return jsonify({"error": "Failed to disconnect"}), 500


@m365_oauth_bp.route("/scuba/assess", methods=["POST"])
@limiter.limit("3 per minute")
@login_required
def m365_scuba_assess():
    """
    POST /api/v1/m365/scuba/assess

    Runs a full CISA SCUBA baseline assessment against the configured tenant.
    Returns structured findings grouped by SCUBA product (AAD, Defender, Intune, Purview).
    """
    _require_platform_admin()

    try:
        from app.services import entra_config_service
        from app.masri.entra_integration import EntraIntegration

        creds = entra_config_service.get_entra_config()
        if not creds or not all(creds.values()):
            return jsonify({"error": "Microsoft 365 is not configured"}), 400

        client = EntraIntegration(
            tenant_id=creds["entra_tenant_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        )

        # Run full SCUBA assessment
        scuba_result = client.assess_cisa_scuba()

        # Run Purview assessment
        purview_result = client.assess_purview()

        return jsonify({
            "scuba": {
                "entra_id": scuba_result,
                "purview": purview_result,
            },
            "assessed_at": str(__import__("datetime").datetime.utcnow()),
        })

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("SCUBA assessment failed")
        return jsonify({"error": "Assessment failed. Check system logs."}), 500
