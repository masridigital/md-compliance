"""
Masri Digital Compliance Platform — Settings API Routes (Phase 1)

Flask Blueprint for all settings-related endpoints: platform config,
tenant branding, LLM, storage providers, SSO, notifications, due dates,
and MCP API keys.
"""

import logging
from flask import Blueprint, jsonify, request, abort, current_app
from flask_login import current_user
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer
from app import db, limiter
from app.masri.settings_service import SettingsService
from app.masri.schemas import (
    validate_payload,
    PlatformSettingsUpdateSchema,
    TenantBrandingUpdateSchema,
    LLMConfigUpdateSchema,
    StorageProviderUpdateSchema,
    SSOConfigUpdateSchema,
    NotificationChannelUpdateSchema,
    MCPKeyCreateSchema,
)
from app.masri.new_models import (
    PlatformSettings,
    TenantBranding,
    SettingsLLM,
    SettingsStorage,
    SettingsSSO,
    SettingsNotifications,
    SettingsEntra,
    DueDate,
    MCPAPIKey,
)

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings_bp", __name__, url_prefix="/api/v1/settings")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin():
    """
    Abort 403 if the current user is not a platform admin (super user).

    Returns the current_user on success so callers can chain:
        user = _require_admin()
    """
    if not getattr(current_user, "super", False):
        abort(403, description="Admin access required")
    return current_user


def _get_json_body():
    """Return parsed JSON body or abort 400 if missing / invalid."""
    data = request.get_json(silent=True)
    if not data:
        abort(400, description="Request body must be valid JSON")
    return data


# ===========================================================================
# Platform Settings (admin only)
# ===========================================================================

@settings_bp.route("/platform", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_platform_settings():
    """GET /api/v1/settings/platform — retrieve singleton platform settings."""
    _require_admin()
    try:
        ps = SettingsService.get_platform_settings()
        return jsonify(ps.as_dict())
    except Exception as e:
        logger.exception("Error fetching platform settings")
        return jsonify({"error": "Failed to retrieve platform settings"}), 500


@settings_bp.route("/platform", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_platform_settings():
    """PUT /api/v1/settings/platform — update platform settings fields."""
    _require_admin()
    data, err = validate_payload(PlatformSettingsUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        ps = SettingsService.update_platform_settings(data)
        return jsonify(ps.as_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating platform settings")
        return jsonify({"error": "Failed to update platform settings"}), 500


# ===========================================================================
# Tenant Branding
# ===========================================================================

@settings_bp.route("/tenants/<string:tenant_id>/branding", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_tenant_branding(tenant_id):
    """GET /api/v1/settings/tenants/<tenant_id>/branding — merged with defaults."""
    Authorizer(current_user).can_user_access_tenant(tenant_id)
    try:
        branding = SettingsService.get_tenant_branding(tenant_id)
        return jsonify(branding)
    except Exception as e:
        logger.exception("Error fetching tenant branding for %s", tenant_id)
        return jsonify({"error": "Failed to retrieve tenant branding"}), 500


@settings_bp.route("/tenants/<string:tenant_id>/branding", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_tenant_branding(tenant_id):
    """PUT /api/v1/settings/tenants/<tenant_id>/branding — update overrides."""
    Authorizer(current_user).can_user_admin_tenant(tenant_id)
    data, err = validate_payload(TenantBrandingUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        tb = SettingsService.update_tenant_branding(tenant_id, data)
        return jsonify(tb.as_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating tenant branding for %s", tenant_id)
        return jsonify({"error": "Failed to update tenant branding"}), 500


# ===========================================================================
# LLM Config (admin only)
# ===========================================================================

@settings_bp.route("/llm", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_llm_config():
    """GET /api/v1/settings/llm — active LLM config with masked api_key."""
    _require_admin()
    try:
        llm = SettingsService.get_active_llm_config()
        if llm is None:
            return jsonify({"message": "No active LLM configuration found"}), 404
        data = llm.as_dict()
        # Mask api_key if present (as_dict already strips api_key_enc,
        # but add explicit masking for safety)
        data.pop("api_key", None)
        data.pop("api_key_enc", None)
        return jsonify(data)
    except Exception as e:
        logger.exception("Error fetching LLM config")
        return jsonify({"error": "Failed to retrieve LLM configuration"}), 500


@settings_bp.route("/llm", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_llm_config():
    """PUT /api/v1/settings/llm — update LLM provider settings."""
    _require_admin()
    data, err = validate_payload(LLMConfigUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        llm = SettingsService.update_llm_config(data)
        result = llm.as_dict()
        result.pop("api_key", None)
        result.pop("api_key_enc", None)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating LLM config")
        return jsonify({"error": "Failed to update LLM configuration"}), 500


# ===========================================================================
# Storage (admin only)
# ===========================================================================

@settings_bp.route("/storage", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_storage_providers():
    """GET /api/v1/settings/storage — list all storage provider configs."""
    _require_admin()
    try:
        providers = db.session.execute(db.select(SettingsStorage)).scalars().all()
        return jsonify([p.as_dict() for p in providers])
    except Exception as e:
        logger.exception("Error listing storage providers")
        return jsonify({"error": "Failed to list storage providers"}), 500


@settings_bp.route("/storage/<string:provider>", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_storage_provider(provider):
    """GET /api/v1/settings/storage/<provider> — specific provider config."""
    _require_admin()
    try:
        record = db.session.execute(db.select(SettingsStorage).filter_by(provider=provider)).scalars().first()
        if record is None:
            return jsonify({"error": f"Storage provider '{provider}' not found"}), 404
        return jsonify(record.as_dict())
    except Exception as e:
        logger.exception("Error fetching storage provider %s", provider)
        return jsonify({"error": "Failed to retrieve storage provider"}), 500


@settings_bp.route("/storage/<string:provider>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_storage_provider(provider):
    """PUT /api/v1/settings/storage/<provider> — update provider config."""
    _require_admin()
    data, err = validate_payload(StorageProviderUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        record = SettingsService.update_storage_provider(provider, data)
        return jsonify(record.as_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating storage provider %s", provider)
        return jsonify({"error": "Failed to update storage provider"}), 500


# ===========================================================================
# SSO (admin only)
# ===========================================================================

@settings_bp.route("/sso", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_sso_config():
    """GET /api/v1/settings/sso — SSO configuration. Use ?tenant_id for per-tenant."""
    tenant_id = request.args.get("tenant_id")
    if tenant_id:
        Authorizer(current_user).can_user_access_tenant(tenant_id)
    else:
        _require_admin()
    try:
        sso = SettingsService.get_sso_config(tenant_id=tenant_id)
        if sso is None:
            return jsonify({"message": "No SSO configuration found"}), 404
        return jsonify(sso.as_dict())
    except Exception as e:
        logger.exception("Error fetching SSO config")
        return jsonify({"error": "Failed to retrieve SSO configuration"}), 500


@settings_bp.route("/sso", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_sso_config():
    """PUT /api/v1/settings/sso — update SSO settings. Include tenant_id in body for per-tenant."""
    data, err = validate_payload(SSOConfigUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    tenant_id = data.pop("tenant_id", None)
    if tenant_id:
        Authorizer(current_user).can_user_access_tenant(tenant_id)
    else:
        _require_admin()
    try:
        sso = SettingsService.update_sso_config(data, tenant_id=tenant_id)
        return jsonify(sso.as_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating SSO config")
        return jsonify({"error": "Failed to update SSO configuration"}), 500


# ===========================================================================
# Notifications
# ===========================================================================

@settings_bp.route("/notifications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_notification_channels():
    """GET /api/v1/settings/notifications — list channels, optionally by tenant."""
    tenant_id = request.args.get("tenant_id")
    if tenant_id:
        auth_result = Authorizer(current_user).can_user_admin_tenant(tenant_id)
        if not auth_result["success"]:
            return jsonify({"error": "Unauthorized"}), 403
    else:
        # No tenant scope → platform-level config; requires platform admin.
        _require_admin()
    try:
        channels = SettingsService.get_notification_channels(tenant_id=tenant_id)
        return jsonify([ch.as_dict() for ch in channels])
    except Exception as e:
        logger.exception("Error fetching notification channels")
        return jsonify({"error": "Failed to retrieve notification channels"}), 500


@settings_bp.route("/notifications/<string:channel>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_notification_channel(channel):
    """PUT /api/v1/settings/notifications/<channel> — update channel config."""
    data, err = validate_payload(NotificationChannelUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    tenant_id = data.pop("tenant_id", None)
    if tenant_id:
        auth_result = Authorizer(current_user).can_user_admin_tenant(tenant_id)
        if not auth_result["success"]:
            return jsonify({"error": "Unauthorized"}), 403
    else:
        # No tenant scope → platform-level config; requires platform admin.
        _require_admin()
    try:
        record = SettingsService.update_notification_channel(
            channel, data, tenant_id=tenant_id
        )
        return jsonify(record.as_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating notification channel %s", channel)
        return jsonify({"error": "Failed to update notification channel"}), 500


# ===========================================================================
# Due Dates
# ===========================================================================

@settings_bp.route("/tenants/<string:tenant_id>/due-dates", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_due_dates(tenant_id):
    """GET /api/v1/settings/tenants/<tenant_id>/due-dates — list due dates."""
    Authorizer(current_user).can_user_access_tenant(tenant_id)

    status = request.args.get("status")
    days_ahead = request.args.get("days_ahead", type=int)

    try:
        due_dates = SettingsService.get_due_dates(
            tenant_id, status=status, days_ahead=days_ahead
        )
        return jsonify([dd.as_dict() for dd in due_dates])
    except Exception as e:
        logger.exception("Error fetching due dates for tenant %s", tenant_id)
        return jsonify({"error": "Failed to retrieve due dates"}), 500


@settings_bp.route(
    "/tenants/<string:tenant_id>/due-dates/check-overdue", methods=["POST"]
)
@limiter.limit("30 per minute")
@login_required
def check_overdue(tenant_id):
    """POST /api/v1/settings/tenants/<tenant_id>/due-dates/check-overdue"""
    Authorizer(current_user).can_user_admin_tenant(tenant_id)
    try:
        newly_overdue = SettingsService.check_and_flag_overdue(tenant_id=tenant_id)
        return jsonify({
            "flagged_count": len(newly_overdue),
            "items": [dd.as_dict() for dd in newly_overdue],
        })
    except Exception as e:
        logger.exception("Error checking overdue items for tenant %s", tenant_id)
        return jsonify({"error": "Failed to check overdue items"}), 500


# ===========================================================================
# MCP API Keys (admin only)
# ===========================================================================

@settings_bp.route("/mcp-keys", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_mcp_keys():
    """GET /api/v1/settings/mcp-keys — list all MCP API keys for the tenant."""
    _require_admin()
    try:
        tenant_id = request.args.get("tenant_id")
        stmt = db.select(MCPAPIKey)
        if tenant_id:
            stmt = stmt.filter_by(tenant_id=tenant_id)
        stmt = stmt.order_by(MCPAPIKey.date_added.desc())
        keys = db.session.execute(stmt).scalars().all()
        return jsonify([k.as_dict() for k in keys])
    except Exception as e:
        logger.exception("Error listing MCP API keys")
        return jsonify({"error": "Failed to list MCP API keys"}), 500


@settings_bp.route("/mcp-keys", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_mcp_key():
    """POST /api/v1/settings/mcp-keys — generate a new MCP API key.

    The raw key is returned ONCE in this response and cannot be retrieved again.
    """
    _require_admin()
    data, err = validate_payload(MCPKeyCreateSchema, request.get_json(silent=True))
    if err:
        return err

    name = data.get("name")
    tenant_id = data.get("tenant_id")
    scopes = data.get("scopes")
    expires_at = data.get("expires_at")

    try:
        key_instance, client_id, client_secret = MCPAPIKey.generate(
            name=name,
            user_id=current_user.id,
            tenant_id=tenant_id,
            scopes=scopes,
            expires_at=expires_at,
        )
        db.session.add(key_instance)
        db.session.commit()

        response = key_instance.as_dict()
        response["client_id"] = client_id
        response["client_secret"] = client_secret
        response["raw_key"] = client_secret  # backward compat
        return jsonify(response), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error generating MCP API key")
        db.session.rollback()
        return jsonify({"error": "Failed to generate MCP API key"}), 500


@settings_bp.route("/mcp-keys/<string:key_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_mcp_key(key_id):
    """DELETE /api/v1/settings/mcp-keys/<key_id> — revoke/delete an MCP API key."""
    _require_admin()
    try:
        key = db.session.get(MCPAPIKey, key_id)
        if key is None:
            return jsonify({"error": "MCP API key not found"}), 404

        db.session.delete(key)
        db.session.commit()
        return jsonify({"message": "MCP API key revoked", "id": key_id})
    except Exception as e:
        logger.exception("Error deleting MCP API key %s", key_id)
        db.session.rollback()
        return jsonify({"error": "Failed to delete MCP API key"}), 500


# ---------------------------------------------------------------------------
# Entra ID credentials (encrypted at rest)
# ---------------------------------------------------------------------------

@settings_bp.route("/llm/models", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def fetch_llm_models():
    """POST /api/v1/settings/llm/models — fetch available models from a provider.

    Body (JSON):
        provider    (str, required) — openai, anthropic, together, azure_openai
        api_key     (str, required) — API key for the provider
    """
    _require_admin()
    data = _get_json_body()
    provider = data.get("provider", "").strip()
    api_key = data.get("api_key", "").strip()

    if not provider or not api_key:
        return jsonify({"error": "provider and api_key are required"}), 400

    try:
        models = _fetch_models_for_provider(provider, api_key)
        return jsonify({"models": models})
    except Exception as e:
        logger.warning("Failed to fetch models for %s: %s", provider, e)
        return jsonify({"error": str(e)}), 502


def _fetch_models_for_provider(provider: str, api_key: str) -> list:
    """Call the provider API and return a list of model ID strings."""
    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.models.list()
        models = sorted(
            [m.id for m in resp.data if any(
                kw in m.id for kw in ("gpt-", "o1", "o3", "o4")
            )],
            key=lambda x: x,
        )
        return models if models else sorted([m.id for m in resp.data])

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.models.list(limit=100)
        return sorted([m.id for m in resp.data])

    elif provider == "together":
        import requests as _requests
        resp = _requests.get(
            "https://api.together.xyz/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        model_list = data if isinstance(data, list) else data.get("data", data.get("models", []))
        chat_models = [
            m["id"] for m in model_list
            if isinstance(m, dict) and m.get("id") and
            m.get("type", "chat") in ("chat", "language", "")
        ]
        return sorted(chat_models) if chat_models else sorted(
            [m["id"] for m in model_list if isinstance(m, dict) and m.get("id")]
        )

    elif provider == "azure_openai":
        return []

    else:
        return []


@settings_bp.route("/entra", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_entra_config():
    """GET /api/v1/settings/entra — return Entra config status (no raw credentials)."""
    from flask import current_app
    _require_admin()
    record = db.session.execute(
        db.select(SettingsEntra).filter_by(tenant_id=None)
    ).scalars().first()

    if record is None:
        # Check env var fallback so the UI can show what source is active
        has_env = all([
            current_app.config.get("ENTRA_TENANT_ID"),
            current_app.config.get("ENTRA_CLIENT_ID"),
            current_app.config.get("ENTRA_CLIENT_SECRET"),
        ])
        return jsonify({
            "configured": False,
            "source": "env_vars" if has_env else "none",
            "has_env_vars": has_env,
        })

    data = record.as_dict()
    data["source"] = "database"
    data["has_env_vars"] = all([
        current_app.config.get("ENTRA_TENANT_ID"),
        current_app.config.get("ENTRA_CLIENT_ID"),
        current_app.config.get("ENTRA_CLIENT_SECRET"),
    ])
    return jsonify(data)


@settings_bp.route("/entra", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def update_entra_config():
    """
    POST /api/v1/settings/entra — save Entra credentials encrypted in the DB.

    Body (JSON):
        entra_tenant_id  (str, required)
        client_id        (str, required)
        client_secret    (str, required)
    """
    _require_admin()
    data = request.get_json(silent=True) or {}

    entra_tenant_id = data.get("entra_tenant_id", "").strip()
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()

    if not all([entra_tenant_id, client_id, client_secret]):
        return jsonify({"error": "entra_tenant_id, client_id, and client_secret are all required"}), 400

    try:
        record = SettingsService.update_entra_config(entra_tenant_id, client_id, client_secret)
        return jsonify(record.as_dict())
    except Exception:
        logger.exception("Error saving Entra credentials")
        db.session.rollback()
        return jsonify({"error": "Failed to save Entra credentials"}), 500


@settings_bp.route("/entra", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def delete_entra_config():
    """DELETE /api/v1/settings/entra — remove stored Entra credentials from the DB."""
    _require_admin()
    record = db.session.execute(
        db.select(SettingsEntra).filter_by(tenant_id=None)
    ).scalars().first()

    if record is None:
        return jsonify({"message": "No Entra credentials stored in database"}), 200

    db.session.delete(record)
    db.session.commit()
    return jsonify({"message": "Entra credentials removed from database"})


# ===========================================================================
# TOTP 2FA (user self-service)
# ===========================================================================

@settings_bp.route("/mfa/setup", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def mfa_setup():
    """POST /api/v1/settings/mfa/setup — generate TOTP secret, return QR URI."""
    secret = current_user.setup_totp()
    uri = current_user.get_totp_uri(
        app_name=current_app.config.get("APP_NAME", "MD Compliance")
    )
    return jsonify({"secret": secret, "uri": uri, "email": current_user.email})


@settings_bp.route("/mfa/verify", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def mfa_verify():
    """POST /api/v1/settings/mfa/verify — verify a TOTP code to enable MFA."""
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "code is required"}), 400

    if current_user.verify_totp(code):
        current_user.enable_totp()
        return jsonify({"message": "MFA enabled successfully", "enabled": True})
    return jsonify({"error": "Invalid code. Please try again."}), 400


@settings_bp.route("/mfa/disable", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def mfa_disable():
    """POST /api/v1/settings/mfa/disable — disable MFA for current user."""
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()

    # Require a valid code to disable (prevents unauthorized disable)
    if current_user.totp_enabled:
        if not code or not current_user.verify_totp(code):
            return jsonify({"error": "Valid TOTP code required to disable MFA"}), 400

    current_user.disable_totp()
    return jsonify({"message": "MFA disabled", "enabled": False})


@settings_bp.route("/mfa/status", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def mfa_status():
    """GET /api/v1/settings/mfa/status — check MFA status for current user."""
    return jsonify({
        "enabled": current_user.totp_enabled,
        "has_secret": bool(current_user.totp_secret_enc),
    })


@settings_bp.route("/mfa/reset/<string:user_id>", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def mfa_admin_reset(user_id):
    """POST /api/v1/settings/mfa/reset/<user_id> — admin resets a user's MFA."""
    _require_admin()
    from app.models import User
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    user.disable_totp()
    return jsonify({"message": f"MFA reset for {user.email}", "enabled": False})


# ===========================================================================
# User Profile
# ===========================================================================

@settings_bp.route("/profile", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_profile():
    """GET /api/v1/settings/profile — current user profile."""
    data = current_user.as_dict()
    data["totp_enabled"] = current_user.totp_enabled
    data["session_timeout_minutes"] = current_user.session_timeout_minutes
    return jsonify(data)


@settings_bp.route("/profile", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_profile():
    """PUT /api/v1/settings/profile — update current user profile."""
    data = request.get_json(silent=True) or {}

    if "first_name" in data:
        current_user.first_name = data["first_name"]
    if "last_name" in data:
        current_user.last_name = data["last_name"]
    if "session_timeout_minutes" in data:
        timeout = int(data["session_timeout_minutes"])
        if timeout in (5, 15, 30, 45, 60, 120, 480):
            current_user.session_timeout_minutes = timeout
            # Also update session
            from flask import session
            session["_user_timeout_minutes"] = timeout

    db.session.commit()
    return jsonify({"message": "Profile updated"})


# ===========================================================================
# Platform Updates
# ===========================================================================

@settings_bp.route("/updates/check", methods=["GET"])
@limiter.limit("10 per minute")
@login_required
def check_updates():
    """GET /api/v1/settings/updates/check — check for available updates."""
    _require_admin()
    from app.masri.update_manager import UpdateManager
    return jsonify(UpdateManager.check())


@settings_bp.route("/updates/apply", methods=["POST"])
@limiter.limit("3 per minute")
@login_required
def apply_updates():
    """POST /api/v1/settings/updates/apply — pull and apply updates."""
    _require_admin()
    from app.masri.update_manager import UpdateManager
    from app.models import Logs
    Logs.add(
        message=f"{current_user.email} triggered platform update",
        action="PUT",
        namespace="system",
        user_id=current_user.id,
    )
    return jsonify(UpdateManager.apply())


@settings_bp.route("/updates/schedule", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_update_schedule():
    """GET /api/v1/settings/updates/schedule — get auto-update config."""
    _require_admin()
    from app.masri.update_manager import UpdateManager
    return jsonify(UpdateManager.get_schedule())


@settings_bp.route("/updates/schedule", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_update_schedule():
    """PUT /api/v1/settings/updates/schedule — configure auto-updates."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    from app.masri.update_manager import UpdateManager
    schedule = UpdateManager.set_schedule(
        enabled=data.get("enabled", False),
        frequency=data.get("frequency", "daily"),
        auto_apply=data.get("auto_apply", False),
    )
    return jsonify(schedule)


# ===========================================================================
# SMTP / Email Configuration
# ===========================================================================

@settings_bp.route("/smtp", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_smtp_config():
    """GET /api/v1/settings/smtp — get current SMTP configuration."""
    _require_admin()
    return jsonify({
        "mail_server": current_app.config.get("MAIL_SERVER", ""),
        "mail_port": current_app.config.get("MAIL_PORT", 587),
        "mail_use_tls": current_app.config.get("MAIL_USE_TLS", True),
        "mail_username": current_app.config.get("MAIL_USERNAME", ""),
        "mail_default_sender": current_app.config.get("MAIL_DEFAULT_SENDER", ""),
        "has_password": bool(current_app.config.get("MAIL_PASSWORD")),
    })


@settings_bp.route("/smtp", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def update_smtp_config():
    """PUT /api/v1/settings/smtp — update SMTP settings (saved to DB + runtime)."""
    _require_admin()
    data = request.get_json(silent=True) or {}

    from app.models import ConfigStore

    # Save each SMTP setting to ConfigStore
    smtp_fields = {
        "MAIL_SERVER": data.get("mail_server"),
        "MAIL_PORT": str(data.get("mail_port", 587)),
        "MAIL_USE_TLS": str(data.get("mail_use_tls", True)),
        "MAIL_USERNAME": data.get("mail_username"),
        "MAIL_DEFAULT_SENDER": data.get("mail_default_sender"),
    }
    for key, value in smtp_fields.items():
        if value is not None:
            ConfigStore.upsert(f"smtp_{key}", str(value))
            current_app.config[key] = value if key != "MAIL_PORT" else int(value)

    # Handle password separately (encrypt)
    if data.get("mail_password"):
        from app.masri.settings_service import encrypt_value
        ConfigStore.upsert("smtp_MAIL_PASSWORD", encrypt_value(data["mail_password"]))
        current_app.config["MAIL_PASSWORD"] = data["mail_password"]

    # Reinitialize Flask-Mail with new config
    try:
        from app import mail
        mail.init_app(current_app._get_current_object())
    except Exception as e:
        logger.warning("Failed to reinitialize mail: %s", e)

    return jsonify({"message": "SMTP configuration saved"})


@settings_bp.route("/smtp/test", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def test_smtp():
    """POST /api/v1/settings/smtp/test — send a test email."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    recipient = data.get("to", current_user.email)

    try:
        from app.email import send_email
        send_email(
            to=recipient,
            subject=f"{current_app.config.get('APP_NAME', 'MD Compliance')} — SMTP Test",
            template="test_email",
            content="This is a test email to verify your SMTP configuration is working correctly.",
        )
        return jsonify({"message": f"Test email sent to {recipient}"})
    except Exception as e:
        return jsonify({"error": f"Failed to send: {str(e)}"}), 500
