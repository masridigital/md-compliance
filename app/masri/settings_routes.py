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
from app import db
from app.masri.settings_service import SettingsService
from app.masri.new_models import (
    PlatformSettings,
    TenantBranding,
    SettingsLLM,
    SettingsStorage,
    SettingsSSO,
    SettingsNotifications,
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
@login_required
def update_platform_settings():
    """PUT /api/v1/settings/platform — update platform settings fields."""
    _require_admin()
    data = _get_json_body()
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
@login_required
def update_tenant_branding(tenant_id):
    """PUT /api/v1/settings/tenants/<tenant_id>/branding — update overrides."""
    Authorizer(current_user).can_user_admin_tenant(tenant_id)
    data = _get_json_body()
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
@login_required
def update_llm_config():
    """PUT /api/v1/settings/llm — update LLM provider settings."""
    _require_admin()
    data = _get_json_body()
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
@login_required
def update_storage_provider(provider):
    """PUT /api/v1/settings/storage/<provider> — update provider config."""
    _require_admin()
    data = _get_json_body()
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
@login_required
def get_sso_config():
    """GET /api/v1/settings/sso — platform-level SSO configuration."""
    _require_admin()
    try:
        sso = SettingsService.get_sso_config()
        if sso is None:
            return jsonify({"message": "No SSO configuration found"}), 404
        return jsonify(sso.as_dict())
    except Exception as e:
        logger.exception("Error fetching SSO config")
        return jsonify({"error": "Failed to retrieve SSO configuration"}), 500


@settings_bp.route("/sso", methods=["PUT"])
@login_required
def update_sso_config():
    """PUT /api/v1/settings/sso — update platform-level SSO settings."""
    _require_admin()
    data = _get_json_body()
    try:
        sso = SettingsService.update_sso_config(data)
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
@login_required
def get_notification_channels():
    """GET /api/v1/settings/notifications — list channels, optionally by tenant."""
    tenant_id = request.args.get("tenant_id")
    try:
        channels = SettingsService.get_notification_channels(tenant_id=tenant_id)
        return jsonify([ch.as_dict() for ch in channels])
    except Exception as e:
        logger.exception("Error fetching notification channels")
        return jsonify({"error": "Failed to retrieve notification channels"}), 500


@settings_bp.route("/notifications/<string:channel>", methods=["PUT"])
@login_required
def update_notification_channel(channel):
    """PUT /api/v1/settings/notifications/<channel> — update channel config."""
    data = _get_json_body()
    tenant_id = data.pop("tenant_id", None)
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
@login_required
def create_mcp_key():
    """POST /api/v1/settings/mcp-keys — generate a new MCP API key.

    The raw key is returned ONCE in this response and cannot be retrieved again.
    """
    _require_admin()
    data = _get_json_body()

    name = data.get("name")
    if not name:
        return jsonify({"error": "Field 'name' is required"}), 400

    tenant_id = data.get("tenant_id")
    scopes = data.get("scopes")
    expires_at = data.get("expires_at")

    try:
        key_instance, raw_key = MCPAPIKey.generate(
            name=name,
            user_id=current_user.id,
            tenant_id=tenant_id,
            scopes=scopes,
            expires_at=expires_at,
        )
        db.session.add(key_instance)
        db.session.commit()

        response = key_instance.as_dict()
        response["raw_key"] = raw_key
        return jsonify(response), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error generating MCP API key")
        db.session.rollback()
        return jsonify({"error": "Failed to generate MCP API key"}), 500


@settings_bp.route("/mcp-keys/<string:key_id>", methods=["DELETE"])
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
