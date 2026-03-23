"""
Masri Digital Compliance Platform — Configuration Additions

Additional config entries to merge into the existing gapps Config class.
These can be added to config.py or loaded via environment variables.

Usage in existing config.py:
    from app.masri.config_additions import MASRI_CONFIG
    ...
    class Config:
        ...
        # Merge Masri additions
        for k, v in MASRI_CONFIG.items():
            locals()[k] = v
"""

import os

MASRI_CONFIG = {
    # ---- Branding defaults ----
    "APP_NAME": os.environ.get("APP_NAME", "Masri Digital"),
    "APP_LOGO_URL": os.environ.get("APP_LOGO_URL", "/static/img/logo.svg"),
    "APP_FAVICON_URL": os.environ.get("APP_FAVICON_URL", "/static/img/favicon.ico"),
    "APP_PRIMARY_COLOR": os.environ.get("APP_PRIMARY_COLOR", "#0066CC"),
    "SUPPORT_EMAIL": os.environ.get("SUPPORT_EMAIL", "inquiry@masridigital.com"),

    # ---- Storage ----
    "STORAGE_PROVIDERS": ["local", "s3", "azure_blob", "sharepoint", "egnyte"],
    "STORAGE_METHOD": os.environ.get("STORAGE_METHOD", "local"),
    "STORAGE_LOCAL_PATH": os.environ.get("STORAGE_LOCAL_PATH", "uploads"),

    # S3
    "S3_BUCKET": os.environ.get("S3_BUCKET", ""),
    "S3_REGION": os.environ.get("S3_REGION", "us-east-1"),
    "S3_ACCESS_KEY": os.environ.get("S3_ACCESS_KEY", ""),
    "S3_SECRET_KEY": os.environ.get("S3_SECRET_KEY", ""),
    "S3_ENDPOINT_URL": os.environ.get("S3_ENDPOINT_URL", ""),

    # Azure Blob
    "AZURE_BLOB_CONNECTION_STRING": os.environ.get("AZURE_BLOB_CONNECTION_STRING", ""),
    "AZURE_BLOB_CONTAINER": os.environ.get("AZURE_BLOB_CONTAINER", ""),

    # SharePoint
    "SHAREPOINT_TENANT_ID": os.environ.get("SHAREPOINT_TENANT_ID", ""),
    "SHAREPOINT_CLIENT_ID": os.environ.get("SHAREPOINT_CLIENT_ID", ""),
    "SHAREPOINT_CLIENT_SECRET": os.environ.get("SHAREPOINT_CLIENT_SECRET", ""),
    "SHAREPOINT_SITE_URL": os.environ.get("SHAREPOINT_SITE_URL", ""),

    # Egnyte
    "EGNYTE_DOMAIN": os.environ.get("EGNYTE_DOMAIN", ""),
    "EGNYTE_ACCESS_TOKEN": os.environ.get("EGNYTE_ACCESS_TOKEN", ""),

    # ---- LLM ----
    "LLM_ENABLED": os.environ.get("LLM_ENABLED", "false").lower() == "true",
    "LLM_PROVIDER": os.environ.get("LLM_PROVIDER", "openai"),
    "LLM_MODEL": os.environ.get("LLM_MODEL", "gpt-4o"),
    "LLM_API_KEY": os.environ.get("LLM_API_KEY", ""),
    "LLM_AZURE_ENDPOINT": os.environ.get("LLM_AZURE_ENDPOINT", ""),
    "LLM_AZURE_DEPLOYMENT": os.environ.get("LLM_AZURE_DEPLOYMENT", ""),
    "LLM_OLLAMA_BASE_URL": os.environ.get("LLM_OLLAMA_BASE_URL", "http://localhost:11434"),
    "LLM_TOKEN_BUDGET_PER_TENANT": int(os.environ.get("LLM_TOKEN_BUDGET_PER_TENANT", "1000000")),
    "LLM_RATE_LIMIT_PER_HOUR": int(os.environ.get("LLM_RATE_LIMIT_PER_HOUR", "100")),

    # ---- SSO ----
    "SSO_ENABLED": os.environ.get("SSO_ENABLED", "false").lower() == "true",
    "SSO_PROVIDER": os.environ.get("SSO_PROVIDER", ""),
    "SSO_CLIENT_ID": os.environ.get("SSO_CLIENT_ID", ""),
    "SSO_CLIENT_SECRET": os.environ.get("SSO_CLIENT_SECRET", ""),
    "SSO_DISCOVERY_URL": os.environ.get("SSO_DISCOVERY_URL", ""),
    "SSO_ALLOW_LOCAL_FALLBACK": os.environ.get("SSO_ALLOW_LOCAL_FALLBACK", "true").lower() == "true",
    "SSO_MFA_REQUIRED": os.environ.get("SSO_MFA_REQUIRED", "false").lower() == "true",
    "SSO_SESSION_TIMEOUT_MINUTES": int(os.environ.get("SSO_SESSION_TIMEOUT_MINUTES", "480")),

    # ---- Notifications ----
    "NOTIFICATIONS_TEAMS_WEBHOOK": os.environ.get("NOTIFICATIONS_TEAMS_WEBHOOK", ""),
    "NOTIFICATIONS_SLACK_WEBHOOK": os.environ.get("NOTIFICATIONS_SLACK_WEBHOOK", ""),
    "NOTIFICATIONS_EMAIL_ENABLED": os.environ.get("NOTIFICATIONS_EMAIL_ENABLED", "true").lower() == "true",
    "NOTIFICATIONS_SMS_PROVIDER": os.environ.get("NOTIFICATIONS_SMS_PROVIDER", ""),
    "NOTIFICATIONS_SMS_API_KEY": os.environ.get("NOTIFICATIONS_SMS_API_KEY", ""),
    "NOTIFICATIONS_SMS_FROM": os.environ.get("NOTIFICATIONS_SMS_FROM", ""),

    # ---- MCP ----
    "MCP_ENABLED": os.environ.get("MCP_ENABLED", "false").lower() == "true",
    "MCP_RATE_LIMIT_PER_MINUTE": int(os.environ.get("MCP_RATE_LIMIT_PER_MINUTE", "60")),

    # ---- WISP ----
    "WISP_ENABLED": os.environ.get("WISP_ENABLED", "true").lower() == "true",

    # ---- Framework files ----
    "MASRI_FRAMEWORK_FOLDER": os.environ.get(
        "MASRI_FRAMEWORK_FOLDER",
        os.path.join(os.path.dirname(__file__), "frameworks"),
    ),

    # ---- Feature flags (extend existing) ----
    "FEATURE_MASRI_SETTINGS": os.environ.get("FEATURE_MASRI_SETTINGS", "true").lower() == "true",
    "FEATURE_MASRI_BRANDING": os.environ.get("FEATURE_MASRI_BRANDING", "true").lower() == "true",
    "FEATURE_MASRI_STORAGE": os.environ.get("FEATURE_MASRI_STORAGE", "true").lower() == "true",
    "FEATURE_MASRI_LLM": os.environ.get("FEATURE_MASRI_LLM", "false").lower() == "true",
    "FEATURE_MASRI_SSO": os.environ.get("FEATURE_MASRI_SSO", "false").lower() == "true",
    "FEATURE_MASRI_MCP": os.environ.get("FEATURE_MASRI_MCP", "false").lower() == "true",
    "FEATURE_MASRI_WISP": os.environ.get("FEATURE_MASRI_WISP", "true").lower() == "true",
    "FEATURE_MASRI_NOTIFICATIONS": os.environ.get("FEATURE_MASRI_NOTIFICATIONS", "true").lower() == "true",
}
