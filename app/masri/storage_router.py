"""
Masri Digital Compliance Platform — Storage Router

Routes file operations to the correct storage provider based on:
1. File role (evidence, reports, backups)
2. Configured provider assignments
3. Fallback chain (configured provider → local)

Design principles:
- Zero config = local storage works (no setup needed)
- One provider = everything goes there
- Multiple providers = each assigned to a role
- Provider failure = automatic fallback to local
- Never lose a file

Roles:
- evidence: User-uploaded evidence files (screenshots, docs, configs)
- reports: Generated compliance reports (WISP, audit, Telivy PDFs)
- backups: Integration data snapshots, DB exports

Usage::

    from app.masri.storage_router import store_file, get_file, get_file_url

    # Store evidence — goes to the provider assigned to "evidence" role
    path = store_file(file_data, "screenshot.png", "projects/abc123", role="evidence")

    # Get file back
    data = get_file(path, role="evidence")

    # Get shareable URL (for auditors)
    url = get_file_url(path, role="evidence", expires_hours=24)
"""

import logging
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)


# Role → provider assignment stored in ConfigStore("storage_role_config")
# Format: {"evidence": "s3", "reports": "azure_blob", "backups": "s3"}
# If not set, all roles use the default provider.
# If no default, all roles use local.

def _get_role_config():
    """Load role → provider mapping from ConfigStore."""
    try:
        from app.models import ConfigStore
        record = ConfigStore.find("storage_role_config")
        if record and record.value:
            return json.loads(record.value)
    except Exception:
        pass
    return {}


def _get_provider_for_role(role):
    """Determine which storage provider to use for a given role.

    Priority:
    1. "Same for all" setting (_sameProvider)
    2. Explicit role assignment in storage_role_config
    3. Default provider (marked is_default in SettingsStorage)
    4. Local filesystem
    """
    role_config = _get_role_config()

    # Check "same for all" first
    if role_config.get("_sameForAll") and role_config.get("_sameProvider"):
        return role_config["_sameProvider"]

    # Check role-specific assignment
    provider_name = role_config.get(role)

    # Fall back to default provider
    if not provider_name:
        provider_name = role_config.get("default")

    if not provider_name:
        try:
            from app.masri.settings_service import SettingsService
            default = SettingsService.get_default_storage_provider()
            if default:
                provider_name = default.provider
        except Exception:
            pass

    # Final fallback
    if not provider_name:
        provider_name = "local"

    return provider_name


def _get_provider_instance(provider_name, tenant_id=None):
    """Instantiate a storage provider from its DB config.

    Returns (provider_instance, provider_name) or (LocalStorageProvider, "local") on failure.
    """
    from app.masri.storage_providers import get_storage_provider, LocalStorageProvider

    if provider_name == "local":
        from flask import current_app
        base = current_app.config.get("EVIDENCE_PATH",
               os.path.join(current_app.root_path, "files", "evidence"))
        return LocalStorageProvider(base_path=base), "local"

    # Load config from DB
    try:
        from app.masri.settings_service import SettingsService
        config = SettingsService.get_storage_provider_config(provider_name)
        if config:
            return get_storage_provider(provider_name, config, tenant_id=tenant_id), provider_name
    except Exception as e:
        logger.warning("Failed to instantiate storage provider %s: %s", provider_name, e)

    # Fallback to local
    logger.warning("Falling back to local storage (provider %s unavailable)", provider_name)
    from flask import current_app
    base = current_app.config.get("EVIDENCE_PATH",
           os.path.join(current_app.root_path, "files", "evidence"))
    return LocalStorageProvider(base_path=base), "local"


def store_file(file_data, file_name, folder, role="evidence", tenant_id=None):
    """Store a file using the provider assigned to the given role.

    Args:
        file_data: bytes or file-like object
        file_name: filename (e.g., "screenshot.png")
        folder: logical folder (e.g., "projects/abc123")
        role: "evidence", "reports", or "backups"
        tenant_id: for per-tenant isolation

    Returns:
        dict with: path, provider, stored_at, file_name, role
    """
    provider_name = _get_provider_for_role(role)
    provider, actual_provider = _get_provider_instance(provider_name, tenant_id)

    try:
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(file_name) or "unnamed_file"
        # Sanitize folder — remove traversal sequences
        safe_folder = "/".join(
            p for p in folder.replace("\\", "/").split("/")
            if p and p != ".." and p != "."
        )

        # Ensure file_data is a file-like object
        if isinstance(file_data, bytes):
            import io
            file_data = io.BytesIO(file_data)

        path = provider.upload_file(file_data, safe_name, safe_folder)

        result = {
            "path": path,
            "provider": actual_provider,
            "file_name": file_name,
            "folder": folder,
            "role": role,
            "stored_at": datetime.utcnow().isoformat(),
        }

        logger.info("Stored %s via %s: %s", role, actual_provider, path)
        return result

    except Exception as e:
        logger.error("Storage failed for %s via %s: %s", role, actual_provider, e)

        # Try configured fallback provider first, then local
        role_config = _get_role_config()
        fallback_name = role_config.get("fallback", "local")
        if fallback_name == actual_provider:
            fallback_name = "local"

        if actual_provider != fallback_name:
            logger.warning("Retrying with fallback storage: %s", fallback_name)
            try:
                fb_provider, fb_name = _get_provider_instance(fallback_name, tenant_id)

                if isinstance(file_data, bytes):
                    import io
                    file_data = io.BytesIO(file_data)
                elif hasattr(file_data, 'seek'):
                    file_data.seek(0)

                path = fb_provider.upload_file(file_data, safe_name, safe_folder)
                return {
                    "path": path,
                    "provider": fb_name,
                    "file_name": file_name,
                    "folder": folder,
                    "role": role,
                    "stored_at": datetime.utcnow().isoformat(),
                    "fallback": True,
                    "original_provider": actual_provider,
                }
            except Exception as e2:
                logger.error("Local fallback also failed: %s", e2)

        raise RuntimeError(f"Failed to store file: {file_name}")


def get_file(path, role="evidence", provider_name=None, tenant_id=None):
    """Retrieve a file's contents.

    Args:
        path: the path returned by store_file()
        role: used to determine provider if provider_name not given
        provider_name: explicit provider (from evidence record)
        tenant_id: for per-tenant isolation

    Returns:
        bytes
    """
    if not provider_name:
        provider_name = _get_provider_for_role(role)

    provider, _ = _get_provider_instance(provider_name, tenant_id)
    return provider.get_file(path)


def delete_file(path, role="evidence", provider_name=None, tenant_id=None):
    """Delete a file.

    Args:
        path: the path returned by store_file()
        role: used to determine provider if provider_name not given
        provider_name: explicit provider
        tenant_id: for per-tenant isolation

    Returns:
        bool
    """
    if not provider_name:
        provider_name = _get_provider_for_role(role)

    provider, _ = _get_provider_instance(provider_name, tenant_id)
    try:
        return provider.delete_file(path)
    except Exception as e:
        logger.warning("Failed to delete %s from %s: %s", path, provider_name, e)
        return False


def get_file_url(path, role="evidence", provider_name=None, tenant_id=None,
                  expires_hours=24):
    """Get a shareable URL for a file (for auditor access).

    Returns URL string or None if provider doesn't support URLs.
    """
    if not provider_name:
        provider_name = _get_provider_for_role(role)

    provider, _ = _get_provider_instance(provider_name, tenant_id)

    # Check if provider supports URL generation
    if hasattr(provider, 'get_file_url'):
        try:
            return provider.get_file_url(path, expires_hours=expires_hours)
        except Exception:
            pass
    elif hasattr(provider, 'generate_sas_url'):
        try:
            return provider.generate_sas_url(path, expires_hours=expires_hours)
        except Exception:
            pass

    return None


def get_storage_status():
    """Get overview of storage configuration for the UI.

    Returns:
        dict with configured providers, role assignments, health status.
    """
    role_config = _get_role_config()
    roles = ["evidence", "reports", "backups"]

    status = {
        "roles": {},
        "providers": [],
        "healthy": True,
    }

    for role in roles:
        provider_name = _get_provider_for_role(role)
        status["roles"][role] = {
            "provider": provider_name,
            "explicitly_assigned": role in role_config,
        }

    # List configured providers
    try:
        from app import db
        from app.masri.new_models import SettingsStorage
        providers = db.session.execute(
            db.select(SettingsStorage).filter(
                SettingsStorage.provider != "telivy"
            )
        ).scalars().all()
        for p in providers:
            status["providers"].append({
                "name": p.provider,
                "enabled": p.enabled,
                "is_default": p.is_default,
            })
    except Exception:
        pass

    if not status["providers"]:
        status["providers"].append({"name": "local", "enabled": True, "is_default": True})

    return status
