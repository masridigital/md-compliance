"""
Masri Digital Compliance Platform — Settings Service Layer

Centralised service for reading/writing platform settings, tenant branding,
storage configs, LLM configs, due dates, and MCP API keys.

All encryption uses Fernet derived from Flask SECRET_KEY.
"""

import json
import base64
import hashlib
import logging
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encryption utilities
# ---------------------------------------------------------------------------

def _get_fernet(app=None):
    """
    Derive a Fernet key from the Flask SECRET_KEY.

    Fernet requires a URL-safe base64 32-byte key. We SHA-256 the SECRET_KEY
    to guarantee exactly 32 bytes, then base64-encode it.
    """
    from flask import current_app
    secret = (app or current_app).config["SECRET_KEY"].encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_value(value: str, app=None) -> str:
    """Encrypt a plaintext string. Returns a Fernet token (str)."""
    f = _get_fernet(app)
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str, app=None) -> str:
    """Decrypt a Fernet token back to plaintext."""
    from cryptography.fernet import InvalidToken
    f = _get_fernet(app)
    try:
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Unable to decrypt stored value — key mismatch or data corruption. "
            "Re-encrypt the setting after rotating SECRET_KEY."
        )


def is_encrypted(value: str) -> bool:
    """
    Return True if ``value`` looks like a Fernet token.

    Fernet tokens are URL-safe base64 and always start with the version byte
    (0x80) which encodes to ``gA`` in base64. All real tokens are much longer
    than 32 characters, so a quick length + prefix check is a reliable heuristic.
    """
    if not value or not isinstance(value, str):
        return False
    if len(value) < 32:
        return False
    try:
        import base64 as _b64
        raw = _b64.urlsafe_b64decode(value[:4] + "==")
        return raw[0] == 0x80
    except Exception:
        return False


# ---------------------------------------------------------------------------
# EncryptedText — SQLAlchemy TypeDecorator for transparent field encryption
# ---------------------------------------------------------------------------

class EncryptedText(TypeDecorator):
    """
    A SQLAlchemy column type that transparently Fernet-encrypts values on
    write and decrypts on read.

    Usage in a model::

        from app.masri.settings_service import EncryptedText
        notes = db.Column(EncryptedText)

    Behaviour:
    - On write: plaintext → Fernet token stored in the DB
    - On read:  if the stored value is already a Fernet token → decrypt it
                if the stored value is plaintext (pre-migration row) → return as-is
    - NULL values pass through untouched.

    Searchability: because Fernet uses a random nonce, encrypted values cannot
    be used in WHERE / ORDER BY / LIKE clauses. Index the column only if you
    need exact-match on the raw (encrypted) bytes — which is never useful.
    For columns that must be queryable (e.g. unique constraints) keep them
    plaintext or use a deterministic hash side-column.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt before writing to the DB."""
        if value is None:
            return value
        value = str(value)
        # Already encrypted (e.g. value passed through twice) — don't double-encrypt.
        if is_encrypted(value):
            return value
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        """Decrypt after reading from the DB; fall back to plaintext for legacy rows."""
        if value is None:
            return value
        if not is_encrypted(value):
            # Pre-migration plaintext row — return as-is; will be encrypted on next save.
            return value
        try:
            return decrypt_value(value)
        except Exception:
            # Key rotation or corruption: surface the raw token rather than crashing.
            logger.warning("EncryptedText: failed to decrypt value, returning raw token.")
            return value


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class SettingsService:
    """
    Stateless service façade for all settings-related operations.

    All methods are @staticmethod so they can be called without instantiation:
        SettingsService.get_platform_settings()
    """

    # ----- PlatformSettings (singleton) -----

    @staticmethod
    def get_platform_settings():
        """
        Returns the singleton PlatformSettings row.
        Creates a default row if the table is empty.
        """
        from app import db
        from app.masri.new_models import PlatformSettings

        ps = db.session.execute(db.select(PlatformSettings)).scalars().first()
        if ps is None:
            ps = PlatformSettings()
            db.session.add(ps)
            db.session.commit()
        return ps

    @staticmethod
    def update_platform_settings(data: dict):
        """
        Validates allowed fields and saves.

        Args:
            data: dict of field -> value. Only fields listed in
                  PlatformSettings.ALLOWED_FIELDS are accepted.

        Returns:
            Updated PlatformSettings instance.
        """
        from app import db
        from app.masri.new_models import PlatformSettings

        ps = SettingsService.get_platform_settings()
        for key, value in data.items():
            if key in PlatformSettings.ALLOWED_FIELDS:
                setattr(ps, key, value)
        db.session.commit()
        return ps

    # ----- TenantBranding -----

    @staticmethod
    def get_tenant_branding(tenant_id: str) -> dict:
        """
        Returns TenantBranding merged with PlatformSettings defaults.

        If a TenantBranding row exists for this tenant, its non-null fields
        override the platform defaults. Otherwise, plain PlatformSettings
        values are returned.

        Returns:
            dict with keys: logo_url, primary_color, app_name, etc.
        """
        from app import db
        from app.masri.new_models import TenantBranding

        ps = SettingsService.get_platform_settings()
        base = {
            "app_name": ps.app_name,
            "logo_url": ps.logo_url,
            "favicon_url": ps.favicon_url,
            "primary_color": ps.primary_color,
            "support_email": ps.support_email,
            "footer_text": ps.footer_text,
            "login_headline": ps.login_headline,
            "login_subheadline": ps.login_subheadline,
            "login_bg_color": ps.login_bg_color,
            "report_header_style": "logo_and_name",
        }

        tb = db.session.execute(db.select(TenantBranding).filter_by(tenant_id=tenant_id)).scalars().first()
        if tb:
            overrides = tb.as_dict()
            for key in ("logo_url", "primary_color", "subdomain",
                        "welcome_message", "email_sender_name",
                        "report_header_style"):
                if overrides.get(key):
                    base[key] = overrides[key]

        return base

    @staticmethod
    def update_tenant_branding(tenant_id: str, data: dict):
        """
        Create or update TenantBranding for a given tenant.

        Returns:
            TenantBranding instance.
        """
        from app import db
        from app.masri.new_models import TenantBranding

        tb = db.session.execute(db.select(TenantBranding).filter_by(tenant_id=tenant_id)).scalars().first()
        if tb is None:
            tb = TenantBranding(tenant_id=tenant_id)
            db.session.add(tb)

        allowed = {"logo_url", "primary_color", "subdomain",
                    "welcome_message", "email_sender_name",
                    "report_header_style"}
        for key, value in data.items():
            if key in allowed:
                setattr(tb, key, value)
        db.session.commit()
        return tb

    # ----- LLM -----

    @staticmethod
    def get_active_llm_config():
        """
        Returns the first enabled SettingsLLM record, or None.
        """
        from app import db
        from app.masri.new_models import SettingsLLM
        return db.session.execute(db.select(SettingsLLM).filter_by(enabled=True)).scalars().first()

    @staticmethod
    def update_llm_config(data: dict):
        """
        Create or update the LLM settings row.

        If 'api_key' is present in data it is encrypted before storage.
        """
        from app import db
        from app.masri.new_models import SettingsLLM

        llm = db.session.execute(db.select(SettingsLLM)).scalars().first()
        if llm is None:
            llm = SettingsLLM()
            db.session.add(llm)

        safe_fields = {"provider", "model_name", "azure_endpoint",
                        "azure_deployment", "ollama_base_url", "enabled",
                        "token_budget_per_tenant", "rate_limit_per_hour"}
        for key, value in data.items():
            if key in safe_fields:
                setattr(llm, key, value)

        if "api_key" in data and data["api_key"]:
            llm.set_api_key(data["api_key"])

        db.session.commit()
        return llm

    # ----- Storage -----

    @staticmethod
    def get_storage_provider_config(provider: str) -> dict:
        """
        Returns decrypted config dict for the named storage provider,
        or None if the provider is not configured.
        """
        from app import db
        from app.masri.new_models import SettingsStorage
        record = db.session.execute(db.select(SettingsStorage).filter_by(provider=provider)).scalars().first()
        if record is None:
            return None
        return record.get_config()

    @staticmethod
    def update_storage_provider(provider: str, data: dict):
        """
        Create or update a storage provider config.

        Args:
            provider: one of SettingsStorage.VALID_PROVIDERS
            data: dict with 'enabled', 'is_default', and 'config' (dict of
                  provider-specific settings like bucket, region, etc.)
        """
        from app import db
        from app.masri.new_models import SettingsStorage

        record = db.session.execute(db.select(SettingsStorage).filter_by(provider=provider)).scalars().first()
        if record is None:
            record = SettingsStorage(provider=provider)
            db.session.add(record)

        if "enabled" in data:
            record.enabled = data["enabled"]
        if "is_default" in data:
            # Unset previous default if this one is becoming default
            if data["is_default"]:
                db.session.execute(
                    db.update(SettingsStorage).where(
                        SettingsStorage.id != record.id
                    ).values(is_default=False)
                )
            record.is_default = data["is_default"]
        if "config" in data and isinstance(data["config"], dict):
            record.save_config(data["config"])

        db.session.commit()
        return record

    @staticmethod
    def get_default_storage_provider():
        """Returns the SettingsStorage marked as default, or None."""
        from app import db
        from app.masri.new_models import SettingsStorage
        return db.session.execute(db.select(SettingsStorage).filter_by(is_default=True)).scalars().first()

    # ----- SSO -----

    @staticmethod
    def get_sso_config():
        """Returns the platform-level SSO config (tenant_id IS NULL)."""
        from app import db
        from app.masri.new_models import SettingsSSO
        return db.session.execute(db.select(SettingsSSO).filter_by(tenant_id=None)).scalars().first()

    @staticmethod
    def update_sso_config(data: dict):
        """Create or update platform-level SSO settings."""
        from app import db
        from app.masri.new_models import SettingsSSO

        sso = db.session.execute(db.select(SettingsSSO).filter_by(tenant_id=None)).scalars().first()
        if sso is None:
            sso = SettingsSSO()
            db.session.add(sso)

        safe_fields = {"provider", "client_id", "discovery_url", "enabled",
                        "allow_local_fallback", "mfa_required",
                        "session_timeout_minutes"}
        for key, value in data.items():
            if key in safe_fields:
                setattr(sso, key, value)

        if "client_secret" in data and data["client_secret"]:
            sso.set_client_secret(data["client_secret"])

        db.session.commit()
        return sso

    # ----- Notifications -----

    @staticmethod
    def get_notification_channels(tenant_id: str = None):
        """Returns all notification channel configs, optionally filtered by tenant."""
        from app import db
        from app.masri.new_models import SettingsNotifications
        stmt = db.select(SettingsNotifications)
        if tenant_id:
            stmt = stmt.filter(
                (SettingsNotifications.tenant_id == tenant_id) |
                (SettingsNotifications.tenant_id.is_(None))
            )
        return db.session.execute(stmt).scalars().all()

    @staticmethod
    def update_notification_channel(channel: str, data: dict,
                                     tenant_id: str = None):
        """Create or update a notification channel config."""
        from app import db
        from app.masri.new_models import SettingsNotifications

        record = db.session.execute(db.select(SettingsNotifications).filter_by(
            channel=channel, tenant_id=tenant_id
        )).scalars().first()
        if record is None:
            record = SettingsNotifications(channel=channel, tenant_id=tenant_id)
            db.session.add(record)

        bool_fields = {"enabled", "critical_enabled", "high_enabled",
                        "medium_enabled", "low_enabled"}
        for key, value in data.items():
            if key in bool_fields:
                setattr(record, key, value)

        if "config" in data and isinstance(data["config"], dict):
            record.save_config(data["config"])

        db.session.commit()
        return record

    # ----- Due Dates -----

    @staticmethod
    def get_due_dates(tenant_id: str, status: str = None,
                      days_ahead: int = None) -> list:
        """
        Query DueDate with optional filters.

        Args:
            tenant_id: required
            status: optional filter (pending, completed, overdue, dismissed)
            days_ahead: if set, return only items due within N days from now

        Returns:
            list of DueDate instances
        """
        from app import db
        from app.masri.new_models import DueDate

        stmt = db.select(DueDate).filter_by(tenant_id=tenant_id)
        if status:
            stmt = stmt.filter_by(status=status)
        if days_ahead is not None:
            cutoff = datetime.utcnow() + timedelta(days=days_ahead)
            stmt = stmt.filter(DueDate.due_date <= cutoff)
        return db.session.execute(stmt.order_by(DueDate.due_date.asc())).scalars().all()

    @staticmethod
    def check_and_flag_overdue(tenant_id: str = None) -> list:
        """
        Sets status='overdue' on past-due items that are still 'pending'.

        Args:
            tenant_id: if provided, scope to a single tenant.
                        Otherwise check all tenants.

        Returns:
            list of DueDate instances that were newly marked overdue.
        """
        from app import db
        from app.masri.new_models import DueDate

        stmt = db.select(DueDate).filter_by(status="pending").filter(
            DueDate.due_date < datetime.utcnow()
        )
        if tenant_id:
            stmt = stmt.filter_by(tenant_id=tenant_id)

        newly_overdue = db.session.execute(stmt).scalars().all()
        for dd in newly_overdue:
            dd.status = "overdue"
        if newly_overdue:
            db.session.commit()
        return newly_overdue

    # ----- Entra ID -----

    @staticmethod
    def get_entra_config() -> dict:
        """
        Return decrypted Entra credentials from the DB, or None if not configured.

        Returns:
            dict with 'entra_tenant_id', 'client_id', 'client_secret', or None.
        """
        from app import db
        from app.masri.new_models import SettingsEntra

        record = db.session.execute(
            db.select(SettingsEntra)
            .filter_by(enabled=True, tenant_id=None)
        ).scalars().first()

        if record is None or not record.is_fully_configured():
            return None

        return record.get_credentials()

    @staticmethod
    def update_entra_config(entra_tenant_id: str, client_id: str, client_secret: str):
        """
        Create or update the platform-level Entra credential record.

        All three values are Fernet-encrypted before storage.
        Pass an empty string for client_secret to leave it unchanged.

        Returns:
            SettingsEntra instance.
        """
        from app import db
        from app.masri.new_models import SettingsEntra

        record = db.session.execute(
            db.select(SettingsEntra).filter_by(tenant_id=None)
        ).scalars().first()

        if record is None:
            record = SettingsEntra()
            db.session.add(record)

        record.set_credentials(entra_tenant_id, client_id, client_secret)
        record.enabled = True
        db.session.commit()
        return record

    # ----- MCP API Keys -----

    @staticmethod
    def get_mcp_key(raw_key: str):
        """
        Validates a raw MCP API key string.

        Returns:
            MCPAPIKey instance if valid, else None.
        """
        from app.masri.new_models import MCPAPIKey
        return MCPAPIKey.validate(raw_key)
