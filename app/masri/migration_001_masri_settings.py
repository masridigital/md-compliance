"""Masri Digital Phase 1 — settings, branding, storage, LLM, SSO,
notifications, due dates, WISP, MCP API keys.

Revision ID: masri_001
Revises: <head>
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "masri_001"
down_revision = None  # adjust to actual head revision in the target repo
branch_labels = None
depends_on = None


def upgrade():
    # ---- PlatformSettings (singleton) ----
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("app_name", sa.String(255), server_default="Masri Digital"),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("favicon_url", sa.String(500), nullable=True),
        sa.Column("primary_color", sa.String(20), server_default="#0066CC"),
        sa.Column("support_email", sa.String(255), nullable=True),
        sa.Column("footer_text", sa.String(500), nullable=True),
        sa.Column("login_headline", sa.String(255), nullable=True),
        sa.Column("login_subheadline", sa.String(500), nullable=True),
        sa.Column("login_bg_color", sa.String(20), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    # ---- TenantBranding ----
    op.create_table(
        "tenant_branding",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("primary_color", sa.String(20), nullable=True),
        sa.Column("subdomain", sa.String(100), nullable=True),
        sa.Column("welcome_message", sa.String(500), nullable=True),
        sa.Column("email_sender_name", sa.String(255), nullable=True),
        sa.Column("report_header_style", sa.String(50), server_default="logo_and_name"),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_branding_tenant"),
    )

    # ---- SettingsSSO ----
    op.create_table(
        "settings_sso",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_secret_enc", sa.Text(), nullable=True),
        sa.Column("discovery_url", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="0"),
        sa.Column("allow_local_fallback", sa.Boolean(), server_default="1"),
        sa.Column("mfa_required", sa.Boolean(), server_default="0"),
        sa.Column("session_timeout_minutes", sa.Integer(), server_default="480"),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    # ---- SettingsLLM ----
    op.create_table(
        "settings_llm",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(50), server_default="openai"),
        sa.Column("model_name", sa.String(100), server_default="gpt-4o"),
        sa.Column("api_key_enc", sa.Text(), nullable=True),
        sa.Column("azure_endpoint", sa.String(500), nullable=True),
        sa.Column("azure_deployment", sa.String(255), nullable=True),
        sa.Column("ollama_base_url", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="0"),
        sa.Column("token_budget_per_tenant", sa.Integer(), nullable=True),
        sa.Column("rate_limit_per_hour", sa.Integer(), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    # ---- SettingsStorage ----
    op.create_table(
        "settings_storage",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1"),
        sa.Column("is_default", sa.Boolean(), server_default="0"),
        sa.Column("config_enc", sa.Text(), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", name="uq_settings_storage_provider"),
    )

    # ---- SettingsNotifications ----
    op.create_table(
        "settings_notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0"),
        sa.Column("config_enc", sa.Text(), nullable=True),
        sa.Column("critical_enabled", sa.Boolean(), server_default="1"),
        sa.Column("high_enabled", sa.Boolean(), server_default="1"),
        sa.Column("medium_enabled", sa.Boolean(), server_default="1"),
        sa.Column("low_enabled", sa.Boolean(), server_default="0"),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    # ---- NotificationLog ----
    op.create_table(
        "notification_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("recipient", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), server_default="sent"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload_summary", sa.Text(), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
    )

    # ---- DueDate ----
    op.create_table(
        "due_date",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("assigned_to", sa.String(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("reminder_7d", sa.Boolean(), server_default="1"),
        sa.Column("reminder_3d", sa.Boolean(), server_default="1"),
        sa.Column("reminder_1d", sa.Boolean(), server_default="1"),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_due_date_tenant_status", "due_date", ["tenant_id", "status"])
    op.create_index("ix_due_date_due_date", "due_date", ["due_date"])

    # ---- WISPDocument ----
    op.create_table(
        "wisp_document",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("company_info", sa.Text(), nullable=True),
        sa.Column("security_officer", sa.Text(), nullable=True),
        sa.Column("risk_assessment", sa.Text(), nullable=True),
        sa.Column("data_inventory", sa.Text(), nullable=True),
        sa.Column("access_controls", sa.Text(), nullable=True),
        sa.Column("physical_security", sa.Text(), nullable=True),
        sa.Column("network_security", sa.Text(), nullable=True),
        sa.Column("incident_response", sa.Text(), nullable=True),
        sa.Column("employee_training", sa.Text(), nullable=True),
        sa.Column("review_schedule", sa.Text(), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
        sa.Column("date_updated", sa.DateTime(), nullable=True),
    )

    # ---- WISPVersion ----
    op.create_table(
        "wisp_version",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("wisp_id", sa.String(), sa.ForeignKey("wisp_document.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("change_summary", sa.String(500), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
    )

    # ---- MCPAPIKey ----
    op.create_table(
        "mcp_api_key",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("date_added", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_mcp_api_key_hash", "mcp_api_key", ["key_hash"])


def downgrade():
    op.drop_table("mcp_api_key")
    op.drop_table("wisp_version")
    op.drop_table("wisp_document")
    op.drop_index("ix_due_date_due_date", table_name="due_date")
    op.drop_index("ix_due_date_tenant_status", table_name="due_date")
    op.drop_table("due_date")
    op.drop_table("notification_log")
    op.drop_table("settings_notifications")
    op.drop_table("settings_storage")
    op.drop_table("settings_llm")
    op.drop_table("settings_sso")
    op.drop_table("tenant_branding")
    op.drop_table("platform_settings")
