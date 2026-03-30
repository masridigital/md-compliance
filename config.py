from sqlalchemy.engine.url import make_url
from urllib.parse import urlparse
import os


basedir = os.path.abspath(os.path.dirname(__file__))


def parse_url_with_defaults(url, default_scheme="http", default_port=5000):
    # Ensure the URL has a scheme, add the default if missing
    if "://" not in url:
        url = f"{default_scheme}://{url}"

    # Parse the URL
    parsed_url = urlparse(url)

    # Extract components with defaults
    scheme = parsed_url.scheme or default_scheme
    host_name = parsed_url.hostname or "localhost"

    # If scheme is https, default port to 443
    if scheme == "https" and parsed_url.port is None:
        port = 443
    else:
        port = parsed_url.port or default_port

    # Construct the full URL
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        full_url = f"{scheme}://{host_name}/"
    else:
        full_url = f"{scheme}://{host_name}:{port}/"

    return scheme, host_name, port, full_url


class Config:
    APP_NAME = os.environ.get("APP_NAME", "Gapps")
    APP_SUBTITLE = os.environ.get("APP_SUBTITLE", "")
    CR_YEAR = os.environ.get("CR_YEAR", "2025")
    VERSION = os.environ.get("VERSION", "1.0.0")

    scheme, host_name, port, full_url = parse_url_with_defaults(
        os.environ.get("HOST_NAME", "localhost")
    )
    HOST_NAME = full_url
    SCHEME = scheme
    PORT = port

    LOG_TYPE = os.environ.get("LOG_TYPE", "stream")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    ENABLE_GCP_LOGGING = os.environ.get("ENABLE_GCP_LOGGING", "false").lower() == "true"

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-before-production")
    SQLALCHEMY_COMMIT_ON_TEARDOWN = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = False

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # SESSION_COOKIE_SECURE is set dynamically in ProductionConfig
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = False  # overridden in ProductionConfig

    # Session timeout — default 5 minutes inactivity
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_TIMEOUT_MINUTES", 5)) * 60
    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", 5))
    # Server boot stamp — all sessions created before this are invalidated
    import time as _time
    SERVER_BOOT_STAMP = str(int(_time.time()))
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.googlemail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_DEBUG = os.environ.get("MAIL_DEBUG", "false").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    BASE_DIR = basedir

    # Only allowed if email is configured as well - see "is_self_registration_enabled"
    ENABLE_SELF_REGISTRATION = (
        os.environ.get("ENABLE_SELF_REGISTRATION", "false").lower() == "true"
    )
    DOC_LINK = os.environ.get("DOC_LINK", "https://github.com/masridigital/md-compliance")
    DEFAULT_EMAIL = os.environ.get("DEFAULT_EMAIL", "admin@example.com")
    DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD")
    HELP_EMAIL = os.environ.get("HELP_EMAIL", DEFAULT_EMAIL)

    ENABLE_GOOGLE_AUTH = os.environ.get("ENABLE_GOOGLE_AUTH", "false").lower() == "true"
    ENABLE_MICROSOFT_AUTH = (
        os.environ.get("ENABLE_MICROSOFT_AUTH", "false").lower() == "true"
    )

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
    MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")

    # Max upload size: default 16MB, configurable via env var
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))

    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(basedir, "app/files/reports")
    )
    FRAMEWORK_FOLDER = os.environ.get(
        "FRAMEWORK_FOLDER", os.path.join(basedir, "app/files/base_controls")
    )
    POLICY_FOLDER = os.environ.get(
        "POLICY_FOLDER", os.path.join(basedir, "app/files/base_policies")
    )
    EVIDENCE_FOLDER = os.environ.get(
        "EVIDENCE_FOLDER", os.path.join(basedir, "app/files/evidence")
    )
    UPLOAD_EXTENSIONS = os.environ.get(
        "UPLOAD_EXTENSIONS",
        {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt", ".csv"},
    )

    STORAGE_PROVIDERS = ["local", "s3", "gcs"]

    # GCS storage backend
    STORAGE_METHOD = os.environ.get("STORAGE_METHOD", "local")
    GCS_BUCKET = os.environ.get("GCS_BUCKET")
    GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
    GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    # AWS storage backend
    AWS_BUCKET = os.environ.get("AWS_BUCKET")
    AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY")
    AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY")
    AWS_REGION = os.environ.get("AWS_REGION")

    # AI
    LLM_ENABLED = os.environ.get("LLM_ENABLED", "false").lower() == "true"
    LLM_NAME = os.environ.get("LLM_NAME")
    LLM_TOKEN = os.environ.get("LLM_TOKEN")

    # Integrations
    INTEGRATIONS_BASE_URL = os.environ.get("INTEGRATIONS_BASE_URL", "http://localhost:8080")
    INTEGRATIONS_TOKEN = os.environ.get("INTEGRATIONS_TOKEN")

    # --- Masri Compliance Platform ---
    APP_PRIMARY_COLOR = os.environ.get("APP_PRIMARY_COLOR", "#0066CC")
    APP_LOGO_URL = os.environ.get("APP_LOGO_URL", "/static/img/logo.svg")
    APP_FAVICON_URL = os.environ.get("APP_FAVICON_URL", "/static/img/favicon.ico")
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "inquiry@masridigital.com")

    # Masri Scheduler
    MASRI_SCHEDULER_ENABLED = os.environ.get("MASRI_SCHEDULER_ENABLED", "true").lower() == "true"

    # Masri Notifications
    TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")
    SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

    # Microsoft Entra ID (Azure AD) integration
    ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID")
    ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID")
    ENTRA_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET")

    # Expose certain env vars in front end (DO NOT PLACE SENSITIVE VARS)
    # Use csv (e.g. storage_method,gcs_bucket)
    DEBUG_ENV_VARS = (
        os.environ.get("DEBUG_ENV_VARS", "STORAGE_METHOD").upper().split(",")
    )

    PLAYGROUND_CSS = os.environ.get("PLAYGROUND_CSS")
    LAYOUT = {
        "header": True,
        "footer": False,
        "sidebar": True,
        "second-panel": True,
        "settings-panel": False,
        "sidebar-open": False,
        "y-padding": "py-2 pt-3",
        "x-padding": "px-6 md:px-8 lg:px-10",
        "header-padding": "3",
        "container": False,
        "2xl-breakpoint": False,
        "xl-breakpoint": False,
        "lg-breakpoint": False,
        "hide-app-name": False,
        "header-border": True,
        "fixed-header": True,
    }

    """
    Do not store sensitive data in feature flags.
    Frontend uses $store.currentUser.featureFlags.flag_name
    Backend uses current_app.config["FEATURE_FLAGS"][flag_name]
    # e.g. feature_flag_name=true
    """
    FEATURE_FLAGS = {
        key[len("feature_") :].lower(): value.lower() in ("1", "true", "yes", "on")
        for key, value in os.environ.items()
        if key.lower().startswith("feature_")
    }

    _INSECURE_KEY = "dev-insecure-key-change-before-production"

    @staticmethod
    def init_app(app):
        pass


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    _secret = os.environ.get("SECRET_KEY", "")
    if not _secret or _secret == "change_secret_key":
        raise RuntimeError(
            "SECRET_KEY must be set to a strong random value in production. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("SQLALCHEMY_DATABASE_URI") or "postgresql://db1:changeme@postgres/db1"
    )

    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        _required = {
            "SECRET_KEY": cls._INSECURE_KEY,
            "SQLALCHEMY_DATABASE_URI": "postgresql://db1:changeme@postgres/db1",
        }
        for var, insecure_default in _required.items():
            value = app.config.get(var, "")
            if not value or value == insecure_default:
                raise ValueError(
                    f"Production requires {var} to be set to a strong, non-default value. "
                    f"Generate SECRET_KEY with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
    url = make_url(SQLALCHEMY_DATABASE_URI)
    POSTGRES_HOST = url.host
    POSTGRES_USER = url.username
    POSTGRES_PASSWORD = url.password
    POSTGRES_DB = url.database


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("SQLALCHEMY_DATABASE_URI") or "postgresql://db1:changeme@postgres/db1"
    )
    url = make_url(SQLALCHEMY_DATABASE_URI)
    POSTGRES_HOST = url.host
    POSTGRES_USER = url.username
    POSTGRES_PASSWORD = url.password
    POSTGRES_DB = url.database


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("SQLALCHEMY_DATABASE_URI") or "postgresql://db1:changeme@postgres/db1"
    )
    url = make_url(SQLALCHEMY_DATABASE_URI)
    POSTGRES_HOST = url.host
    POSTGRES_USER = url.username
    POSTGRES_PASSWORD = url.password
    POSTGRES_DB = url.database
    WTF_CSRF_ENABLED = True


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "default": ProductionConfig,
}
