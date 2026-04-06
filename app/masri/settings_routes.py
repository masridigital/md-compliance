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
    """GET /api/v1/settings/llm — current LLM configuration."""
    _require_admin()
    try:
        llm = SettingsService.get_active_llm_config()
        if llm is None:
            # Return empty but valid config
            return jsonify({"provider": "", "model_name": "", "enabled": False, "has_api_key": False})
        data = llm.as_dict()
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
    """PUT /api/v1/settings/llm — update LLM provider settings for a slot."""
    _require_admin()
    data, err = validate_payload(LLMConfigUpdateSchema, request.get_json(silent=True))
    if err:
        return err
    try:
        data.pop("slot", None)  # slot no longer used
        llm = SettingsService.update_llm_config(data)
        result = llm.as_dict()
        result.pop("api_key", None)
        result.pop("api_key_enc", None)
        return jsonify(result)
    except ValueError as e:
        logger.warning("LLM config validation error: %s", e)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Error updating LLM config: %s", e)
        db.session.rollback()
        logger.exception("Failed to save LLM configuration")
        return jsonify({"error": "Failed to save LLM configuration"}), 500


@settings_bp.route("/llm", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def delete_llm_config():
    """DELETE /api/v1/settings/llm — remove the primary LLM provider."""
    _require_admin()
    try:
        from app.masri.new_models import SettingsLLM
        llm = db.session.execute(db.select(SettingsLLM)).scalars().first()
        if llm:
            db.session.delete(llm)
            db.session.commit()
        return jsonify({"message": "Primary provider removed"})
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to delete LLM config: %s", e)
        return jsonify({"error": "Failed to remove provider"}), 500


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


@settings_bp.route("/storage/<string:provider>/test", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def test_storage_provider(provider):
    """POST /api/v1/settings/storage/<provider>/test — test connectivity."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    try:
        if provider == "s3":
            import boto3
            kwargs = {"aws_access_key_id": data.get("access_key"), "aws_secret_access_key": data.get("secret_key"), "region_name": data.get("region", "us-east-1")}
            if data.get("endpoint_url"):
                kwargs["endpoint_url"] = data["endpoint_url"]
            s3 = boto3.client("s3", **kwargs)
            s3.head_bucket(Bucket=data.get("bucket", "test"))
            return jsonify({"message": f"Connected to S3 bucket: {data.get('bucket')}"})

        elif provider == "azure_blob":
            from azure.storage.blob import BlobServiceClient
            conn_str = f"DefaultEndpointsProtocol=https;AccountName={data.get('account_name')};AccountKey={data.get('account_key')};EndpointSuffix=core.windows.net"
            client = BlobServiceClient.from_connection_string(conn_str, connection_timeout=10)
            props = client.get_account_information()
            return jsonify({"message": f"Connected to Azure Storage: {data.get('account_name')}"})

        elif provider == "sharepoint":
            import requests as _requests
            # Test by getting a Graph API token
            token_url = f"https://login.microsoftonline.com/{data.get('tenant_id')}/oauth2/v2.0/token"
            resp = _requests.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": data.get("client_id"),
                "client_secret": data.get("client_secret"),
                "scope": "https://graph.microsoft.com/.default",
            }, timeout=10)
            if resp.ok:
                return jsonify({"message": "SharePoint credentials validated"})
            return jsonify({"error": f"Auth failed: {resp.json().get('error_description', resp.status_code)}"}), 400

        elif provider == "egnyte":
            import requests as _requests
            resp = _requests.get(
                f"https://{data.get('domain')}/pubapi/v1/userinfo",
                headers={"Authorization": f"Bearer {data.get('api_token')}"},
                timeout=10,
            )
            if resp.ok:
                return jsonify({"message": f"Connected to Egnyte: {data.get('domain')}"})
            return jsonify({"error": f"Egnyte auth failed: {resp.status_code}"}), 400

        else:
            return jsonify({"message": "Local storage — no test needed"})

    except ImportError as e:
        return jsonify({"error": f"Missing library: {str(e)}. Install the required package."}), 500
    except Exception as e:
        logger.warning("Storage connection test failed: %s", e)
        return jsonify({"error": "Connection test failed. Check credentials and try again."}), 500


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
    # SSO config changes require admin, not just access
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


@settings_bp.route("/mcp-keys/<string:key_id>/toggle", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def toggle_mcp_key(key_id):
    """PUT /api/v1/settings/mcp-keys/<key_id>/toggle — enable/disable without deleting."""
    _require_admin()
    try:
        key = db.session.get(MCPAPIKey, key_id)
        if key is None:
            return jsonify({"error": "MCP API key not found"}), 404
        data = request.get_json(silent=True) or {}
        key.enabled = data.get("enabled", not key.enabled)
        db.session.commit()
        return jsonify({"message": f"Key {'enabled' if key.enabled else 'disabled'}", "enabled": key.enabled})
    except Exception as e:
        logger.exception("Error toggling MCP key %s", key_id)
        db.session.rollback()
        return jsonify({"error": "Failed to toggle MCP key"}), 500


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

@settings_bp.route("/telivy/mappings", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_telivy_mappings():
    """GET /api/v1/settings/telivy/mappings — get scan-to-tenant mappings."""
    _require_admin()
    try:
        from app.models import ConfigStore
        import json
        record = ConfigStore.find("telivy_scan_mappings")
        if record and record.value:
            return jsonify(json.loads(record.value))
        return jsonify({})
    except Exception:
        return jsonify({})


@settings_bp.route("/telivy/mappings", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_telivy_mappings():
    """PUT /api/v1/settings/telivy/mappings — save scan-to-tenant mappings.

    Accepts either:
      - Simple format: { "scan_id": "tenant_id", ... }
      - Rich format: { "scan_id": { "tenant_id": "...", "data": {...} }, ... }
    """
    _require_admin()
    import json
    from app.models import ConfigStore
    data = request.get_json(silent=True) or {}
    ConfigStore.upsert("telivy_scan_mappings", json.dumps(data))
    return jsonify({"message": "Mappings saved"})


@settings_bp.route("/llm/features", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_llm_feature_models():
    """GET /api/v1/settings/llm/features — get per-feature provider+model routing."""
    _require_admin()
    try:
        from app.models import ConfigStore
        import json
        record = ConfigStore.find("llm_feature_models")
        if record and record.value:
            return jsonify(json.loads(record.value))
        return jsonify({"sameForAll": True, "models": {}})
    except Exception:
        return jsonify({"sameForAll": True, "models": {}})


@settings_bp.route("/llm/features", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_llm_feature_models():
    """PUT /api/v1/settings/llm/features — save tier-based or per-feature routing.

    Tier-based (recommended):
    {
        "sameForAll": false,
        "tiers": {
            "fast": {"provider": "together_ai", "model": "meta-llama/..."},
            "standard": {"provider": "together_ai", "model": "meta-llama/..."},
            "advanced": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
        }
    }

    Legacy per-feature (still supported):
    {
        "sameForAll": false,
        "models": {"auto_map": {"provider": "...", "model": "..."}}
    }
    """
    _require_admin()
    import json
    from app.models import ConfigStore
    data = request.get_json(silent=True) or {}
    ConfigStore.upsert("llm_feature_models", json.dumps({
        "sameForAll": data.get("sameForAll", True),
        "tiers": data.get("tiers", {}),
        "models": data.get("models", {}),
    }))
    return jsonify({"message": "Feature routing saved"})


@settings_bp.route("/llm/providers", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_llm_providers():
    """GET /api/v1/settings/llm/providers — list all configured LLM providers."""
    _require_admin()
    import json
    from app.models import ConfigStore

    providers = []

    # Primary provider from SettingsLLM
    try:
        from app.masri.settings_service import SettingsService
        primary = SettingsService.get_active_llm_config()
        if primary:
            providers.append({
                "key": primary.provider,
                "provider": primary.provider,
                "model": primary.model_name,
                "is_primary": True,
                "has_key": bool(primary.api_key_enc),
            })
    except Exception:
        pass

    # Additional providers from ConfigStore
    try:
        record = ConfigStore.find("llm_additional_providers")
        if record and record.value:
            extras = json.loads(record.value)
            for key, cfg in extras.items():
                providers.append({
                    "key": key,
                    "provider": cfg.get("provider", key),
                    "model": cfg.get("model_name", ""),
                    "is_primary": False,
                    "has_key": bool(cfg.get("api_key_enc")),
                })
    except Exception:
        pass

    return jsonify(providers)


@settings_bp.route("/llm/providers/<string:provider_key>", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_llm_provider(provider_key):
    """PUT /api/v1/settings/llm/providers/<key> — add/update an additional LLM provider.

    Body: { "provider": "anthropic", "model_name": "claude-sonnet-4-20250514", "api_key": "sk-..." }
    """
    _require_admin()
    import json
    from app.models import ConfigStore
    from app.masri.settings_service import encrypt_value

    data = request.get_json(silent=True) or {}
    provider = data.get("provider", provider_key)
    model_name = data.get("model_name", "")
    api_key = data.get("api_key", "")

    # Load existing providers
    extras = {}
    try:
        record = ConfigStore.find("llm_additional_providers")
        if record and record.value:
            extras = json.loads(record.value)
    except Exception:
        pass

    # Build config — single source of truth in llm_additional_providers
    cfg = extras.get(provider_key, {})
    cfg["provider"] = provider
    if model_name:
        cfg["model_name"] = model_name
    if api_key:
        cfg["api_key_enc"] = encrypt_value(api_key)

    extras[provider_key] = cfg
    ConfigStore.upsert("llm_additional_providers", json.dumps(extras))

    return jsonify({"message": f"Provider '{provider_key}' saved"})


@settings_bp.route("/llm/providers/<string:provider_key>", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def delete_llm_provider(provider_key):
    """DELETE /api/v1/settings/llm/providers/<key> — remove an additional provider."""
    _require_admin()
    import json
    from app.models import ConfigStore

    extras = {}
    try:
        record = ConfigStore.find("llm_additional_providers")
        if record and record.value:
            extras = json.loads(record.value)
    except Exception:
        pass

    if provider_key in extras:
        del extras[provider_key]
        ConfigStore.upsert("llm_additional_providers", json.dumps(extras))

    # Remove individual config
    try:
        record = ConfigStore.find(f"llm_provider_{provider_key}")
        if record:
            db.session.delete(record)
            db.session.commit()
    except Exception:
        pass

    return jsonify({"message": f"Provider '{provider_key}' removed"})


@settings_bp.route("/llm/test", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def test_llm_connection():
    """POST /api/v1/settings/llm/test — test connection using SAVED key.

    If api_key is provided in body, uses that. Otherwise uses the saved key.
    """
    _require_admin()
    data = request.get_json(silent=True) or {}
    provider = data.get("provider")
    api_key = data.get("api_key", "").strip()

    # If no key provided, get it from saved config
    if not api_key:
        # First try: additional providers store (single source of truth)
        if provider:
            try:
                from app.models import ConfigStore
                import json as _json
                extras_record = ConfigStore.find("llm_additional_providers")
                if extras_record and extras_record.value:
                    extras = _json.loads(extras_record.value)
                    prov_cfg = extras.get(provider, {})
                    if prov_cfg.get("api_key_enc"):
                        from app.masri.settings_service import decrypt_value
                        api_key = decrypt_value(prov_cfg["api_key_enc"])
            except Exception as e:
                logger.debug("Additional provider key lookup failed for %s: %s", provider, e)

        # Second try: primary provider config (only if same provider or no provider specified)
        if not api_key:
            try:
                llm = SettingsService.get_active_llm_config()
                if llm:
                    if not provider or provider == llm.provider:
                        api_key = llm.get_api_key() or ""
                        if not provider:
                            provider = llm.provider
            except Exception:
                pass

    if not provider:
        return jsonify({"error": "No provider selected."}), 400
    if not api_key:
        return jsonify({"error": f"No API key found for {provider}. Save a key first."}), 400

    try:
        # Quick validation first (fast, validates auth)
        _quick_test_provider(provider, api_key)
        # Auth works — try to get model count (non-blocking, best effort)
        model_count = 0
        try:
            models = _fetch_models_for_provider(provider, api_key)
            model_count = len(models)
        except Exception:
            pass  # Auth is valid, just can't list models right now
        msg = f"Connected! {model_count} models available." if model_count else "Connected!"
        return jsonify({"message": msg, "provider": provider, "model_count": model_count})
    except Exception as e:
        logger.warning("LLM connection test failed for %s: %s", provider, e)
        # Give a more specific error hint
        err_str = str(e).lower()
        if "401" in err_str or "auth" in err_str or "invalid" in err_str:
            return jsonify({"error": "Authentication failed. Check your API key."}), 502
        elif "timeout" in err_str:
            return jsonify({"error": f"Connection timed out for {provider}. Try again."}), 502
        else:
            return jsonify({"error": f"Connection failed for {provider}. Check API key and try again."}), 502


def _quick_test_provider(provider, api_key):
    """Fast connection test — validates API key without fetching full model list."""
    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=api_key, timeout=15.0)
        client.models.list()  # Quick call
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
        client.models.list(limit=1)
    elif provider in ("together", "together_ai"):
        import requests as _requests
        # Use a lightweight chat completion with max_tokens=1 to validate auth
        resp = _requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            timeout=30,
        )
        # 401/403 = bad key, anything else (including model errors) = key works
        if resp.status_code in (401, 403):
            resp.raise_for_status()
    elif provider == "azure_openai":
        pass  # Azure doesn't have a simple test — key validation happens on first use
    else:
        raise ValueError(f"Unknown provider: {provider}")


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

    # Fall back to saved key — single source: llm_additional_providers
    if not api_key and provider:
        try:
            from app.models import ConfigStore
            import json as _json2
            extras_record = ConfigStore.find("llm_additional_providers")
            if extras_record and extras_record.value:
                extras = _json2.loads(extras_record.value)
                prov_cfg = extras.get(provider, {})
                if prov_cfg.get("api_key_enc"):
                    from app.masri.settings_service import decrypt_value
                    api_key = decrypt_value(prov_cfg["api_key_enc"])
        except Exception as e:
            logger.debug("Additional provider key lookup failed for %s: %s", provider, e)

    if not api_key:
        try:
            llm = SettingsService.get_active_llm_config()
            if llm:
                api_key = llm.get_api_key() or ""
                if not provider:
                    provider = llm.provider
        except Exception:
            try:
                from app.masri.new_models import SettingsLLM
                llm = db.session.execute(db.select(SettingsLLM)).scalars().first()
                if llm:
                    if not provider or provider == llm.provider:
                        api_key = llm.get_api_key() or ""
                        if not provider:
                            provider = llm.provider
            except Exception:
                pass

    if not provider:
        return jsonify({"error": "Select a provider first"}), 400
    if not api_key:
        return jsonify({"error": "No API key saved. Enter and save a key first."}), 400

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
        client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
        resp = client.models.list(limit=100)
        return sorted([m.id for m in resp.data])

    elif provider in ("together", "together_ai"):
        import requests as _requests
        # Together AI model list can be slow — use longer timeout with retry
        for attempt in range(3):
            try:
                resp = _requests.get(
                    "https://api.together.xyz/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=60,
                )
                resp.raise_for_status()
                break
            except (_requests.exceptions.ReadTimeout, _requests.exceptions.ConnectionError):
                if attempt < 2:
                    continue
                raise
        data = resp.json()
        model_list = data if isinstance(data, list) else data.get("data", data.get("models", []))
        # Include all models that have an id — Together AI types vary
        all_models = [
            m["id"] for m in model_list
            if isinstance(m, dict) and m.get("id")
        ]
        # Prefer chat/language models if type field exists
        chat_models = [
            m["id"] for m in model_list
            if isinstance(m, dict) and m.get("id") and
            m.get("type", "") in ("chat", "language")
        ]
        return sorted(chat_models) if chat_models else sorted(all_models)

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
# NinjaOne RMM
# ===========================================================================

@settings_bp.route("/ninjaone", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_ninjaone_config():
    """GET /api/v1/settings/ninjaone — return NinjaOne config status."""
    from flask import current_app
    _require_admin()
    try:
        from app.masri.new_models import SettingsStorage
        record = db.session.execute(
            db.select(SettingsStorage).filter_by(provider="ninjaone")
        ).scalars().first()
        if record:
            safe = record.as_dict()
            safe["configured"] = True
            safe["enabled"] = record.enabled
            return jsonify(safe)
    except Exception:
        pass

    has_env = bool(current_app.config.get("NINJAONE_CLIENT_ID"))
    return jsonify({"configured": has_env, "source": "env_vars" if has_env else "none"})


@settings_bp.route("/ninjaone", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def update_ninjaone_config():
    """POST /api/v1/settings/ninjaone — save NinjaOne credentials encrypted."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()
    region = data.get("region", "us").strip().lower()

    if not client_id or not client_secret:
        return jsonify({"error": "client_id and client_secret are required"}), 400
    if region not in ("us", "eu", "ap", "ca"):
        return jsonify({"error": "region must be one of: us, eu, ap, ca"}), 400

    try:
        from app.masri.new_models import SettingsStorage
        import json
        record = db.session.execute(
            db.select(SettingsStorage).filter_by(provider="ninjaone")
        ).scalars().first()
        if not record:
            record = SettingsStorage(provider="ninjaone", enabled=True)
            db.session.add(record)
        record.enabled = True
        record.save_config({"client_id": client_id, "client_secret": client_secret, "region": region})
        db.session.commit()
        return jsonify(record.as_dict())
    except Exception:
        logger.exception("Error saving NinjaOne credentials")
        db.session.rollback()
        return jsonify({"error": "Failed to save NinjaOne credentials"}), 500


@settings_bp.route("/ninjaone", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def delete_ninjaone_config():
    """DELETE /api/v1/settings/ninjaone — remove NinjaOne config."""
    _require_admin()
    try:
        from app.masri.new_models import SettingsStorage
        record = db.session.execute(
            db.select(SettingsStorage).filter_by(provider="ninjaone")
        ).scalars().first()
        if record:
            db.session.delete(record)
            db.session.commit()
        return jsonify({"message": "NinjaOne configuration removed"})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete NinjaOne configuration"}), 500


@settings_bp.route("/ninjaone/mappings", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_ninjaone_mappings():
    """GET /api/v1/settings/ninjaone/mappings — get org→tenant mappings."""
    _require_admin()
    try:
        from app.models import ConfigStore
        import json
        record = ConfigStore.find("ninjaone_org_mappings")
        if record and record.value:
            return jsonify(json.loads(record.value))
        return jsonify({})
    except Exception:
        return jsonify({})


@settings_bp.route("/ninjaone/mappings", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_ninjaone_mappings():
    """PUT /api/v1/settings/ninjaone/mappings — save org→tenant mappings."""
    _require_admin()
    import json
    from app.models import ConfigStore
    data = request.get_json(silent=True) or {}
    ConfigStore.upsert("ninjaone_org_mappings", json.dumps(data))
    return jsonify({"message": "Mappings saved"})


# ===========================================================================
# DefensX Browser Security
# ===========================================================================

@settings_bp.route("/defensx", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_defensx_config():
    """GET /api/v1/settings/defensx — return DefensX config status."""
    from flask import current_app
    _require_admin()
    try:
        from app.masri.new_models import SettingsStorage
        record = db.session.execute(
            db.select(SettingsStorage).filter_by(provider="defensx")
        ).scalars().first()
        if record:
            safe = record.as_dict()
            safe["configured"] = True
            safe["enabled"] = record.enabled
            return jsonify(safe)
    except Exception:
        pass

    has_env = bool(current_app.config.get("DEFENSX_API_TOKEN"))
    return jsonify({"configured": has_env, "source": "env_vars" if has_env else "none"})


@settings_bp.route("/defensx", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def update_defensx_config():
    """POST /api/v1/settings/defensx — save DefensX API token encrypted."""
    _require_admin()
    data = request.get_json(silent=True) or {}
    api_token = data.get("api_token", "").strip()

    if not api_token:
        return jsonify({"error": "api_token is required"}), 400

    try:
        from app.masri.new_models import SettingsStorage
        record = db.session.execute(
            db.select(SettingsStorage).filter_by(provider="defensx")
        ).scalars().first()
        if not record:
            record = SettingsStorage(provider="defensx", enabled=True)
            db.session.add(record)
        record.enabled = True
        record.save_config({"api_token": api_token})
        db.session.commit()
        return jsonify(record.as_dict())
    except Exception:
        logger.exception("Error saving DefensX credentials")
        db.session.rollback()
        return jsonify({"error": "Failed to save DefensX credentials"}), 500


@settings_bp.route("/defensx", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def delete_defensx_config():
    """DELETE /api/v1/settings/defensx — remove DefensX config."""
    _require_admin()
    try:
        from app.masri.new_models import SettingsStorage
        record = db.session.execute(
            db.select(SettingsStorage).filter_by(provider="defensx")
        ).scalars().first()
        if record:
            db.session.delete(record)
            db.session.commit()
        return jsonify({"message": "DefensX configuration removed"})
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to delete DefensX configuration"}), 500


@settings_bp.route("/defensx/mappings", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_defensx_mappings():
    """GET /api/v1/settings/defensx/mappings — get customer→tenant mappings."""
    _require_admin()
    try:
        from app.models import ConfigStore
        import json
        record = ConfigStore.find("defensx_customer_mappings")
        if record and record.value:
            return jsonify(json.loads(record.value))
        return jsonify({})
    except Exception:
        return jsonify({})


@settings_bp.route("/defensx/mappings", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_defensx_mappings():
    """PUT /api/v1/settings/defensx/mappings — save customer→tenant mappings."""
    _require_admin()
    import json
    from app.models import ConfigStore
    data = request.get_json(silent=True) or {}
    ConfigStore.upsert("defensx_customer_mappings", json.dumps(data))
    return jsonify({"message": "Mappings saved"})


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
        app_name = current_app.config.get('APP_NAME', 'MD Compliance')
        send_email(
            subject=f"{app_name} — SMTP Test",
            recipients=[recipient],
            text_body=f"This is a test email from {app_name} to verify your SMTP configuration is working correctly.",
            html_body=f"<h3>{app_name}</h3><p>This is a test email to verify your SMTP configuration is working correctly.</p><p>If you received this, your SMTP settings are configured properly.</p>",
            async_send=False,
        )
        return jsonify({"message": f"Test email sent to {recipient}"})
    except Exception as e:
        logger.exception("SMTP test failed")
        # Return detailed error for troubleshooting
        error_msg = str(e)
        hints = ""
        if "Authentication" in error_msg or "535" in error_msg:
            hints = " Check your username/password. Gmail requires an App Password (not your regular password)."
        elif "Connection refused" in error_msg or "timed out" in error_msg:
            hints = " Check the SMTP server address and port. Common: smtp.gmail.com:587, smtp.office365.com:587"
        elif "STARTTLS" in error_msg or "SSL" in error_msg:
            hints = " Try toggling the TLS setting. Port 587 usually needs TLS on, port 465 needs SSL."
        elif "sender" in error_msg.lower() or "from" in error_msg.lower():
            hints = " Check the Default Sender field — it must be a valid email address."
        return jsonify({"error": f"SMTP test failed: {error_msg}.{hints}"}), 500


# ===========================================================================
# Integration Reset
# ===========================================================================

@settings_bp.route("/reset/<string:integration_type>", methods=["DELETE"])
@limiter.limit("10 per minute")
@login_required
def reset_integration(integration_type):
    """DELETE /api/v1/settings/reset/<type> — clear an integration config.

    Supports:
      - llm (all slots)
      - llm/<slot> (specific slot: 1, 2, 3)
      - storage/<provider> (s3, azure_blob, sharepoint, egnyte, local)
      - entra
      - sso
      - mcp (all keys)
      - smtp
      - notification/<channel> (teams_webhook, slack_webhook, sms)
    """
    _require_admin()
    from app.models import Logs

    parts = integration_type.split("/")
    category = parts[0]
    sub = parts[1] if len(parts) > 1 else None

    try:
        if category == "llm":
            from app.masri.new_models import SettingsLLM
            if sub:
                slot = int(sub)
                rows = db.session.execute(
                    db.select(SettingsLLM).filter_by(slot=slot)
                ).scalars().all()
                if not rows:
                    # Try NULL slot for slot 1
                    rows = db.session.execute(db.select(SettingsLLM)).scalars().all()
                    rows = [r for r in rows if (getattr(r, 'slot', None) or 1) == slot]
                for r in rows:
                    db.session.delete(r)
            else:
                for r in db.session.execute(db.select(SettingsLLM)).scalars().all():
                    db.session.delete(r)

        elif category == "storage":
            from app.masri.new_models import SettingsStorage
            if sub:
                rows = db.session.execute(db.select(SettingsStorage).filter_by(provider=sub)).scalars().all()
            else:
                rows = db.session.execute(db.select(SettingsStorage)).scalars().all()
            for r in rows:
                db.session.delete(r)

        elif category == "entra":
            from app.masri.new_models import SettingsEntra
            for r in db.session.execute(db.select(SettingsEntra)).scalars().all():
                db.session.delete(r)

        elif category == "sso":
            from app.masri.new_models import SettingsSSO
            for r in db.session.execute(db.select(SettingsSSO)).scalars().all():
                db.session.delete(r)

        elif category == "mcp":
            from app.masri.new_models import MCPAPIKey
            for r in db.session.execute(db.select(MCPAPIKey)).scalars().all():
                db.session.delete(r)

        elif category == "smtp":
            from app.models import ConfigStore
            for key in ["smtp_MAIL_SERVER", "smtp_MAIL_PORT", "smtp_MAIL_USE_TLS",
                         "smtp_MAIL_USERNAME", "smtp_MAIL_DEFAULT_SENDER", "smtp_MAIL_PASSWORD"]:
                rec = ConfigStore.find(key)
                if rec:
                    db.session.delete(rec)

        elif category == "notification":
            from app.masri.new_models import SettingsNotifications
            if sub:
                rows = db.session.execute(db.select(SettingsNotifications).filter_by(channel=sub)).scalars().all()
            else:
                rows = db.session.execute(db.select(SettingsNotifications)).scalars().all()
            for r in rows:
                db.session.delete(r)

        else:
            return jsonify({"error": f"Unknown integration type: {integration_type}"}), 400

        db.session.commit()
        Logs.add(message=f"Reset integration: {integration_type}", action="DELETE", namespace="settings", user_id=current_user.id)
        return jsonify({"message": f"{integration_type} configuration cleared"})

    except Exception as e:
        logger.exception("Error resetting integration %s", integration_type)
        db.session.rollback()
        logger.exception("Reset failed for %s", integration_type)
        return jsonify({"error": "Reset failed"}), 500


# ===========================================================================
# System Logs (real-time in-app viewer)
# ===========================================================================

@settings_bp.route("/llm/recommendations", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_model_recommendations():
    """GET /api/v1/settings/llm/recommendations — current model recommendations."""
    _require_admin()
    from app.masri.model_recommender import get_current_recommendations
    recs = get_current_recommendations()
    if recs:
        return jsonify(recs)
    return jsonify({"message": "No recommendations yet. Click refresh to generate."})


@settings_bp.route("/llm/recommendations/refresh", methods=["POST"])
@limiter.limit("3 per minute")
@login_required
def refresh_model_recommendations_endpoint():
    """POST /api/v1/settings/llm/recommendations/refresh — trigger fresh analysis.

    If recommendations were generated within the last 48 hours, returns the
    existing ones instead of re-running the research.
    """
    _require_admin()
    import json as _json
    from datetime import datetime, timedelta

    # Check if fresh recommendations already exist (< 48 hours old)
    try:
        from app.models import ConfigStore
        record = ConfigStore.find("llm_model_recommendations")
        if record and record.value:
            existing = _json.loads(record.value)
            generated_at = existing.get("generated_at")
            if generated_at:
                gen_dt = datetime.fromisoformat(generated_at)
                if datetime.utcnow() - gen_dt < timedelta(hours=48):
                    return jsonify({
                        "message": "Recent recommendations available (less than 48h old). Using cached results.",
                        "skipped": True,
                        **existing,
                    })
    except Exception:
        pass

    import threading
    from flask import current_app
    app = current_app._get_current_object()

    def _run():
        try:
            from app.masri.model_recommender import refresh_model_recommendations
            refresh_model_recommendations(app)
        except Exception as e:
            logger.exception("Model recommendation refresh failed: %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"message": "Recommendation refresh started in background."})


@settings_bp.route("/storage-overview", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_storage_status_endpoint():
    """GET /api/v1/settings/storage-overview — storage configuration overview."""
    _require_admin()
    from app.masri.storage_router import get_storage_status
    return jsonify(get_storage_status())


@settings_bp.route("/storage-roles", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_storage_roles():
    """GET /api/v1/settings/storage-roles — role-to-provider assignments."""
    _require_admin()
    from app.masri.storage_router import _get_role_config
    config = _get_role_config()
    return jsonify(config if config else {
        "evidence": "local",
        "reports": "local",
        "backups": "local",
        "default": "local",
    })


@settings_bp.route("/storage-roles", methods=["PUT"])
@limiter.limit("10 per minute")
@login_required
def set_storage_roles():
    """PUT /api/v1/settings/storage-roles — assign providers to roles.

    Body: { "evidence": "s3", "reports": "azure_blob", "backups": "s3", "default": "local" }
    """
    _require_admin()
    import json
    from app.models import ConfigStore
    data = request.get_json(silent=True) or {}
    # Only allow known roles
    allowed_roles = {"evidence", "reports", "backups", "default"}
    clean = {k: v for k, v in data.items() if k in allowed_roles and isinstance(v, str)}
    ConfigStore.upsert("storage_role_config", json.dumps(clean))
    return jsonify({"message": "Storage role assignments saved", "roles": clean})


@settings_bp.route("/system-logs", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_system_logs():
    """GET /api/v1/settings/system-logs — recent application logs for in-app viewer."""
    _require_admin()
    from app.masri.log_buffer import get_recent_logs

    limit = request.args.get("limit", 200, type=int)
    level = request.args.get("level")
    since = request.args.get("since")

    logs = get_recent_logs(limit=min(limit, 500), level=level, since=since)
    return jsonify(logs)
