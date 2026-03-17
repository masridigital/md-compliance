"""
Masri Digital Compliance Platform — New Models (Phase 1)

Follows exact patterns from gapps models.py:
  - shortuuid PKs (8-char, lowercase)
  - date_added / date_updated columns
  - as_dict() via column iteration
  - db.relationship with cascade="all, delete-orphan"
  - Validators via @validates
"""

from datetime import datetime
from sqlalchemy.orm import validates
from app import db
import shortuuid
import json
import hashlib
import secrets


def _short_id():
    return str(shortuuid.ShortUUID().random(length=8)).lower()


# ---------------------------------------------------------------------------
# Encryption helpers (imported at method level to avoid circular imports)
# ---------------------------------------------------------------------------

def _encrypt(value: str) -> str:
    """Encrypt a string using Fernet derived from SECRET_KEY."""
    from app.masri.settings_service import encrypt_value
    return encrypt_value(value)


def _decrypt(value: str) -> str:
    """Decrypt a Fernet-encrypted string."""
    from app.masri.settings_service import decrypt_value
    return decrypt_value(value)


# ===========================================================================
# PlatformSettings — singleton global config
# ===========================================================================

class PlatformSettings(db.Model):
    """Singleton — global platform config. Always query .first(), create if none."""
    __tablename__ = "platform_settings"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    app_name = db.Column(db.String, default="Masri Digital Compliance")
    app_subtitle = db.Column(
        db.String, default="Information Security for CPA & Law Firms"
    )
    logo_url = db.Column(db.String)
    favicon_url = db.Column(db.String)
    primary_color = db.Column(db.String, default="#0066CC")
    support_email = db.Column(db.String, default="compliance@masridigital.com")
    support_phone = db.Column(db.String)
    login_headline = db.Column(db.String, default="Compliance, simplified.")
    login_subheadline = db.Column(
        db.String, default="Protecting your firm's data."
    )
    login_bg_color = db.Column(db.String, default="#F5F5F7")
    footer_text = db.Column(db.String, default="Powered by Masri Digital")
    show_powered_by = db.Column(db.Boolean, default=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    ALLOWED_FIELDS = {
        "app_name", "app_subtitle", "logo_url", "favicon_url",
        "primary_color", "support_email", "support_phone",
        "login_headline", "login_subheadline", "login_bg_color",
        "footer_text", "show_powered_by",
    }

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data


# ===========================================================================
# TenantBranding — per-tenant customisation overrides
# ===========================================================================

class TenantBranding(db.Model):
    __tablename__ = "tenant_branding"
    __table_args__ = (db.UniqueConstraint("tenant_id"),)

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=False, unique=True
    )
    logo_url = db.Column(db.String)
    primary_color = db.Column(db.String)
    subdomain = db.Column(db.String)
    welcome_message = db.Column(db.String)
    email_sender_name = db.Column(db.String)
    report_header_style = db.Column(db.String, default="logo_and_name")
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_REPORT_STYLES = ["logo_and_name", "logo_only", "name_only", "none"]

    @validates("report_header_style")
    def _validate_report_style(self, key, value):
        if value and value not in self.VALID_REPORT_STYLES:
            raise ValueError(f"Invalid report_header_style: {value}")
        return value

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data


# ===========================================================================
# SettingsSSO
# ===========================================================================

class SettingsSSO(db.Model):
    __tablename__ = "settings_sso"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    provider = db.Column(db.String, default="oidc")
    client_id = db.Column(db.String)
    client_secret_enc = db.Column(db.Text)  # Fernet encrypted
    discovery_url = db.Column(db.String)
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=True
    )  # null = platform-level
    enabled = db.Column(db.Boolean, default=False)
    allow_local_fallback = db.Column(db.Boolean, default=True)
    mfa_required = db.Column(db.Boolean, default=False)
    session_timeout_minutes = db.Column(db.Integer, default=480)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_PROVIDERS = ["oidc", "microsoft", "google", "saml"]

    @validates("provider")
    def _validate_provider(self, key, value):
        if value and value.lower() not in self.VALID_PROVIDERS:
            raise ValueError(f"Invalid SSO provider: {value}")
        return value.lower() if value else "oidc"

    def set_client_secret(self, raw_secret: str):
        """Encrypt and store client secret."""
        self.client_secret_enc = _encrypt(raw_secret)

    def get_client_secret(self) -> str:
        """Decrypt and return client secret."""
        if not self.client_secret_enc:
            return None
        return _decrypt(self.client_secret_enc)

    def as_dict(self):
        """Never expose client_secret_enc."""
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("client_secret_enc", None)
        data["has_client_secret"] = bool(self.client_secret_enc)
        return data


# ===========================================================================
# SettingsLLM
# ===========================================================================

class SettingsLLM(db.Model):
    __tablename__ = "settings_llm"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    provider = db.Column(db.String, default="openai")
    api_key_enc = db.Column(db.Text)  # Fernet encrypted
    model_name = db.Column(db.String, default="gpt-4o")
    azure_endpoint = db.Column(db.String)
    azure_deployment = db.Column(db.String)
    ollama_base_url = db.Column(db.String, default="http://localhost:11434")
    enabled = db.Column(db.Boolean, default=False)
    token_budget_per_tenant = db.Column(db.Integer, default=500)
    rate_limit_per_hour = db.Column(db.Integer, default=100)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_PROVIDERS = ["openai", "anthropic", "azure_openai", "ollama"]

    @validates("provider")
    def _validate_provider(self, key, value):
        if value and value.lower() not in self.VALID_PROVIDERS:
            raise ValueError(f"Invalid LLM provider: {value}")
        return value.lower() if value else "openai"

    def set_api_key(self, raw_key: str):
        self.api_key_enc = _encrypt(raw_key)

    def get_api_key(self) -> str:
        if not self.api_key_enc:
            return None
        return _decrypt(self.api_key_enc)

    def as_dict(self):
        """Never expose api_key_enc."""
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("api_key_enc", None)
        data["has_api_key"] = bool(self.api_key_enc)
        return data


# ===========================================================================
# SettingsStorage
# ===========================================================================

class SettingsStorage(db.Model):
    __tablename__ = "settings_storage"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    provider = db.Column(db.String, nullable=False)
    enabled = db.Column(db.Boolean, default=False)
    is_default = db.Column(db.Boolean, default=False)
    config_enc = db.Column(db.Text)  # Fernet-encrypted JSON
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_PROVIDERS = [
        "local", "s3", "azure_blob", "sharepoint", "egnyte", "gcs"
    ]

    @validates("provider")
    def _validate_provider(self, key, value):
        if value and value.lower() not in self.VALID_PROVIDERS:
            raise ValueError(f"Invalid storage provider: {value}")
        return value.lower() if value else value

    def get_config(self) -> dict:
        """Decrypt config_enc and return as dict."""
        if not self.config_enc:
            return {}
        try:
            return json.loads(_decrypt(self.config_enc))
        except Exception:
            return {}

    def save_config(self, config: dict):
        """Encrypt dict as JSON and store."""
        self.config_enc = _encrypt(json.dumps(config))

    def as_dict(self):
        """Return safe representation — config keys listed but secrets masked."""
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("config_enc", None)
        raw_config = self.get_config()
        safe_config = {}
        secret_keys = {"secret_key", "access_key", "api_key", "api_token",
                        "account_key", "client_secret", "password"}
        for k, v in raw_config.items():
            if any(sk in k.lower() for sk in secret_keys) and v:
                safe_config[k] = "••••••••"
            else:
                safe_config[k] = v
        data["config"] = safe_config
        return data


# ===========================================================================
# SettingsNotifications
# ===========================================================================

class SettingsNotifications(db.Model):
    __tablename__ = "settings_notifications"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    channel = db.Column(db.String, nullable=False)
    enabled = db.Column(db.Boolean, default=False)
    config_enc = db.Column(db.Text)  # Fernet-encrypted JSON
    critical_enabled = db.Column(db.Boolean, default=True)
    high_enabled = db.Column(db.Boolean, default=True)
    medium_enabled = db.Column(db.Boolean, default=True)
    low_enabled = db.Column(db.Boolean, default=False)
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=True
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_CHANNELS = ["email", "teams_webhook", "slack_webhook", "sms", "in_app"]

    @validates("channel")
    def _validate_channel(self, key, value):
        if value and value.lower() not in self.VALID_CHANNELS:
            raise ValueError(f"Invalid notification channel: {value}")
        return value.lower() if value else value

    def get_config(self) -> dict:
        if not self.config_enc:
            return {}
        try:
            return json.loads(_decrypt(self.config_enc))
        except Exception:
            return {}

    def save_config(self, config: dict):
        self.config_enc = _encrypt(json.dumps(config))

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("config_enc", None)
        raw_config = self.get_config()
        safe_config = {}
        secret_keys = {"webhook_url", "api_key", "token", "password",
                        "auth_token", "sid"}
        for k, v in raw_config.items():
            if any(sk in k.lower() for sk in secret_keys) and v:
                safe_config[k] = "••••••••"
            else:
                safe_config[k] = v
        data["config"] = safe_config
        return data


# ===========================================================================
# NotificationLog
# ===========================================================================

class NotificationLog(db.Model):
    __tablename__ = "notification_log"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    channel = db.Column(db.String, nullable=False)
    event_type = db.Column(db.String, nullable=False)
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=True
    )
    target_user_id = db.Column(
        db.String, db.ForeignKey("users.id"), nullable=True
    )
    payload_json = db.Column(db.Text)
    status = db.Column(db.String, default="pending")
    error_message = db.Column(db.Text)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    VALID_STATUSES = ["pending", "sent", "failed"]

    @validates("status")
    def _validate_status(self, key, value):
        if value and value.lower() not in self.VALID_STATUSES:
            raise ValueError(f"Invalid notification status: {value}")
        return value.lower() if value else "pending"

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        return data


# ===========================================================================
# DueDate
# ===========================================================================

class DueDate(db.Model):
    __tablename__ = "due_dates"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    entity_type = db.Column(db.String, nullable=False)
    entity_id = db.Column(db.String, nullable=False)
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=False
    )
    due_date = db.Column(db.DateTime, nullable=False)

    # Reminder preferences
    remind_30d = db.Column(db.Boolean, default=True)
    remind_7d = db.Column(db.Boolean, default=True)
    remind_1d = db.Column(db.Boolean, default=True)
    remind_on_due = db.Column(db.Boolean, default=True)
    remind_when_overdue = db.Column(db.Boolean, default=True)

    # Delivery channels
    deliver_via_teams = db.Column(db.Boolean, default=True)
    deliver_via_email = db.Column(db.Boolean, default=True)

    status = db.Column(db.String, default="pending")
    completed_at = db.Column(db.DateTime, nullable=True)
    assigned_to_user_id = db.Column(
        db.String, db.ForeignKey("users.id"), nullable=True
    )
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_ENTITY_TYPES = [
        "control", "wisp", "risk", "framework_review",
        "pen_test", "vuln_scan", "training",
    ]
    VALID_STATUSES = ["pending", "completed", "overdue", "dismissed"]

    @validates("entity_type")
    def _validate_entity_type(self, key, value):
        if value and value.lower() not in self.VALID_ENTITY_TYPES:
            raise ValueError(f"Invalid entity_type: {value}")
        return value.lower() if value else value

    @validates("status")
    def _validate_status(self, key, value):
        if value and value.lower() not in self.VALID_STATUSES:
            raise ValueError(f"Invalid due date status: {value}")
        return value.lower() if value else "pending"

    def is_overdue(self) -> bool:
        if self.status in ("completed", "dismissed"):
            return False
        return datetime.utcnow() > self.due_date

    def days_until_due(self) -> int:
        delta = self.due_date - datetime.utcnow()
        return delta.days

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["is_overdue"] = self.is_overdue()
        data["days_until_due"] = self.days_until_due()
        return data


# ===========================================================================
# WISPDocument
# ===========================================================================

class WISPDocument(db.Model):
    __tablename__ = "wisp_documents"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=False
    )
    version = db.Column(db.Integer, default=1)
    status = db.Column(db.String, default="draft")

    # Firm info (Step 1)
    firm_name = db.Column(db.String)
    firm_type = db.Column(db.String, nullable=False)
    state_of_incorporation = db.Column(db.String)
    employee_count_range = db.Column(db.String)
    client_record_count_range = db.Column(db.String)

    # Qualified Individual (Step 2)
    qi_name = db.Column(db.String)
    qi_email = db.Column(db.String)
    qi_title = db.Column(db.String)
    qi_is_third_party = db.Column(db.Boolean, default=False)

    # Wizard section data stored as JSON Text (Steps 3–9)
    asset_inventory_json = db.Column(db.Text)
    risk_assessment_json = db.Column(db.Text)
    access_control_answers_json = db.Column(db.Text)
    encryption_answers_json = db.Column(db.Text)
    third_party_vendors_json = db.Column(db.Text)
    incident_response_json = db.Column(db.Text)
    training_program_json = db.Column(db.Text)
    physical_security_json = db.Column(db.Text)
    business_continuity_json = db.Column(db.Text)
    annual_review_json = db.Column(db.Text)

    # LLM-generated policy text per section
    generated_text_json = db.Column(db.Text)

    # Outputs
    signed_by_user_id = db.Column(
        db.String, db.ForeignKey("users.id"), nullable=True
    )
    signed_at = db.Column(db.DateTime, nullable=True)
    pdf_path = db.Column(db.String)
    docx_path = db.Column(db.String)

    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    versions = db.relationship(
        "WISPVersion",
        backref="wisp",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    VALID_STATUSES = ["draft", "active", "archived"]
    VALID_FIRM_TYPES = [
        "cpa_firm", "tax_preparer", "law_firm", "mortgage_lender",
        "mortgage_broker", "financial_advisor", "insurance_agency", "other",
    ]

    SECTION_FIELDS = [
        "firm_name", "qi_name", "asset_inventory_json",
        "risk_assessment_json", "access_control_answers_json",
        "encryption_answers_json", "third_party_vendors_json",
        "incident_response_json", "training_program_json",
    ]

    @validates("status")
    def _validate_status(self, key, value):
        if value and value.lower() not in self.VALID_STATUSES:
            raise ValueError(f"Invalid WISP status: {value}")
        return value.lower() if value else "draft"

    def get_completion_percentage(self) -> int:
        """Sections with non-null data / total sections * 100."""
        total = len(self.SECTION_FIELDS)
        filled = sum(1 for f in self.SECTION_FIELDS if getattr(self, f))
        return int((filled / total) * 100) if total > 0 else 0

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["completion_percentage"] = self.get_completion_percentage()
        json_fields = [
            "asset_inventory_json", "risk_assessment_json",
            "access_control_answers_json", "encryption_answers_json",
            "third_party_vendors_json", "incident_response_json",
            "training_program_json", "physical_security_json",
            "business_continuity_json", "annual_review_json",
            "generated_text_json",
        ]
        for f in json_fields:
            val = data.get(f)
            if val and isinstance(val, str):
                try:
                    data[f] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return data


# ===========================================================================
# WISPVersion
# ===========================================================================

class WISPVersion(db.Model):
    __tablename__ = "wisp_versions"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    wisp_id = db.Column(
        db.String, db.ForeignKey("wisp_documents.id"), nullable=False
    )
    version = db.Column(db.Integer, nullable=False)
    change_summary = db.Column(db.Text)
    snapshot_json = db.Column(db.Text)
    created_by_user_id = db.Column(db.String, db.ForeignKey("users.id"))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        if data.get("snapshot_json") and isinstance(data["snapshot_json"], str):
            try:
                data["snapshot_json"] = json.loads(data["snapshot_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        return data


# ===========================================================================
# MCPAPIKey
# ===========================================================================

class MCPAPIKey(db.Model):
    __tablename__ = "mcp_api_keys"

    id = db.Column(
        db.String,
        primary_key=True,
        default=_short_id,
        unique=True,
    )
    name = db.Column(db.String, nullable=False)
    key_hash = db.Column(db.String, nullable=False)  # SHA-256 hex
    key_prefix = db.Column(db.String(8))  # first 8 chars shown in UI
    tenant_id = db.Column(
        db.String, db.ForeignKey("tenants.id"), nullable=True
    )  # null = platform-level
    user_id = db.Column(
        db.String, db.ForeignKey("users.id"), nullable=False
    )
    scopes_json = db.Column(db.Text)  # JSON list; null = all tools
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    enabled = db.Column(db.Boolean, default=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    @classmethod
    def generate(cls, name: str, user_id: str, tenant_id: str = None,
                 scopes: list = None, expires_at=None):
        """
        Generate a new MCP API key.

        Returns:
            tuple[MCPAPIKey, str]: Model instance and the raw key (shown once).
        """
        raw_key = f"mcp_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]

        instance = cls(
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id=tenant_id,
            user_id=user_id,
            scopes_json=json.dumps(scopes) if scopes else None,
            expires_at=expires_at,
        )
        return instance, raw_key

    @classmethod
    def validate(cls, raw_key: str):
        """
        Validate a raw API key string.

        Returns:
            MCPAPIKey | None
        """
        if not raw_key:
            return None
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        record = cls.query.filter_by(key_hash=key_hash, enabled=True).first()
        if record is None:
            return None
        if record.expires_at and datetime.utcnow() > record.expires_at:
            return None
        record.last_used_at = datetime.utcnow()
        db.session.commit()
        return record

    def get_scopes(self) -> list:
        if not self.scopes_json:
            return None
        try:
            return json.loads(self.scopes_json)
        except (json.JSONDecodeError, TypeError):
            return None

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("key_hash", None)
        data["scopes"] = self.get_scopes()
        data.pop("scopes_json", None)
        return data
