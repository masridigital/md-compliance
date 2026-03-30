from flask import Flask, request, render_template, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from config import config
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from authlib.integrations.flask_client import OAuth
from sqlalchemy import exc
import logging


db = SQLAlchemy()
migrate = Migrate()
mail = Mail()
login = LoginManager()
login.login_view = "auth.get_login"
import os as _os

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=_os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)


def create_app(config_name="default"):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    configure_models(app)
    registering_blueprints(app)
    configure_extensions(app)
    configure_auth_providers(app)
    configure_errors(app)
    configure_logging(app)
    set_config_options(app)
    configure_masri(app)
    configure_security_headers(app)
    _validate_secret_key(app)
    _load_smtp_from_db(app)
    _write_boot_stamp(app)
    _ensure_db_columns(app)

    @app.before_request
    def enforce_session_timeout():
        """
        Enforce inactivity-based session timeout (30 min default).
        Wrapped in try/except so it NEVER crashes a request.
        """
        try:
            from flask_login import current_user, logout_user
            from datetime import datetime, timedelta

            session.permanent = True

            # Skip for static files and auth routes
            if not request.endpoint or request.endpoint.startswith("static"):
                return
            if request.endpoint in (
                "auth.get_login", "auth.login", "auth.get_register",
                "auth.get_verify_totp", "auth.verify_totp", "auth.logout",
            ):
                return

            if not (current_user and current_user.is_authenticated):
                return

            # Force logout on server restart / update
            # Boot stamp is in app.config (memory) — NO database access here
            boot_stamp = app.config.get("_BOOT_STAMP", "")
            session_stamp = session.get("_boot_stamp", "")
            if boot_stamp and session_stamp and session_stamp != boot_stamp:
                # Session was created before this server started — force re-login
                logout_user()
                session.clear()
                return redirect(url_for("auth.get_login"))
            if boot_stamp and not session_stamp:
                # First request after login — stamp the session
                session["_boot_stamp"] = boot_stamp

            # Determine timeout — use session cache only, never touch DB here
            timeout_minutes = int(session.get("_user_timeout_minutes", 0)) or app.config.get("SESSION_TIMEOUT_MINUTES", 30)

            # Check inactivity
            last_activity = session.get("_last_activity")
            if last_activity:
                last_dt = datetime.fromisoformat(last_activity)
                if datetime.utcnow() - last_dt > timedelta(minutes=timeout_minutes):
                    logout_user()
                    session.clear()
                    return redirect(url_for("auth.get_login"))

            # Update activity timestamp
            session["_last_activity"] = datetime.utcnow().isoformat()
        except Exception:
            pass  # NEVER crash a request due to timeout logic

    return app


def _validate_secret_key(app):
    """
    Warn (or raise in non-debug, non-testing mode) if SECRET_KEY is too short.

    Fernet key derivation via PBKDF2 can handle short keys, but short keys
    dramatically reduce the effective key space.  We require at least 32 chars.
    """
    key = app.config.get("SECRET_KEY", "")
    if len(key) < 32:
        msg = (
            "SECRET_KEY is too short (%d chars). "
            "Generate a strong key with: python -c \"import secrets; print(secrets.token_hex(32))\""
        ) % len(key)
        if app.debug or app.testing:
            app.logger.warning("SECURITY WARNING: %s", msg)
        else:
            raise RuntimeError(msg)


def _write_boot_stamp(app):
    """Write a fresh boot stamp to ConfigStore on every server start.

    Any session whose _boot_stamp doesn't match will be forced to re-login.
    This guarantees ALL users are logged out after a server restart or update.
    """
    import time
    stamp = str(int(time.time()))
    try:
        with app.app_context():
            from app.models import ConfigStore
            ConfigStore.upsert("server_boot_stamp", stamp)
            app.config["_BOOT_STAMP"] = stamp
    except Exception:
        app.config["_BOOT_STAMP"] = stamp


def _ensure_db_columns(app):
    """Auto-add missing columns to existing tables so the app works without running migrations."""
    try:
        with app.app_context():
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()

            # Define columns to ensure exist: (table, column, sql_type, default)
            needed = [
                ("settings_llm", "slot", "INTEGER", "1"),
                ("settings_llm", "label", "VARCHAR(255)", "'Primary'"),
                ("users", "totp_secret_enc", "TEXT", "NULL"),
                ("users", "totp_enabled", "BOOLEAN", "false"),
                ("users", "session_timeout_minutes", "INTEGER", "NULL"),
                ("mcp_api_keys", "client_id", "VARCHAR(255)", "NULL"),
                ("tenants", "archived", "BOOLEAN", "false"),
            ]

            for table, column, sql_type, default in needed:
                if table not in tables:
                    continue
                existing = [c["name"] for c in inspector.get_columns(table)]
                if column not in existing:
                    default_clause = f" DEFAULT {default}" if default != "NULL" else ""
                    db.session.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}{default_clause}"
                    ))
                    app.logger.info("Auto-added column %s.%s", table, column)

            db.session.commit()
            app.logger.info("Database column check complete")
    except Exception as e:
        app.logger.warning("Auto-column creation failed: %s — run 'flask db upgrade' to apply migrations", e)
        try:
            db.session.rollback()
        except Exception:
            pass


def _load_smtp_from_db(app):
    """Load SMTP settings from ConfigStore if saved (overrides env defaults)."""
    try:
        with app.app_context():
            from app.models import ConfigStore
            smtp_keys = ["MAIL_SERVER", "MAIL_PORT", "MAIL_USE_TLS", "MAIL_USERNAME", "MAIL_DEFAULT_SENDER"]
            for key in smtp_keys:
                record = ConfigStore.find(f"smtp_{key}")
                if record and record.value:
                    if key == "MAIL_PORT":
                        app.config[key] = int(record.value)
                    elif key == "MAIL_USE_TLS":
                        app.config[key] = record.value.lower() in ("true", "1", "yes")
                    else:
                        app.config[key] = record.value

            # Decrypt password
            pw_record = ConfigStore.find("smtp_MAIL_PASSWORD")
            if pw_record and pw_record.value:
                try:
                    from app.masri.settings_service import decrypt_value
                    app.config["MAIL_PASSWORD"] = decrypt_value(pw_record.value)
                except Exception:
                    pass

            # Reinitialize Flask-Mail
            mail.init_app(app)
    except Exception:
        pass  # DB may not be ready yet (first boot)


def configure_masri(app):
    """Load Masri config additions, context processors, and scheduler."""
    from app.masri.config_additions import MASRI_CONFIG

    for key, value in MASRI_CONFIG.items():
        app.config.setdefault(key, value)

    from app.masri.context_processors import register_context_processors

    register_context_processors(app)

    # Start background scheduler (only in non-testing environments)
    if not app.config.get("TESTING") and app.config.get("MASRI_SCHEDULER_ENABLED", True):
        try:
            from app.masri.scheduler import masri_scheduler
            masri_scheduler.start(app)
        except Exception:
            app.logger.warning("Failed to start Masri scheduler", exc_info=True)


def configure_auth_providers(app):
    oauth = OAuth(app)
    app.providers = {}
    app.providers["google"] = oauth.register(
        name="google",
        client_id=app.config.get("GOOGLE_CLIENT_ID"),
        client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    app.providers["microsoft"] = oauth.register(
        name="microsoft",
        client_id=app.config.get("MICROSOFT_CLIENT_ID"),
        client_secret=app.config.get("MICROSOFT_CLIENT_SECRET"),
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        authorize_params=None,
        access_token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        access_token_params=None,
        client_kwargs={"scope": "openid email profile"},
        jwks_uri="https://login.microsoftonline.com/common/discovery/v2.0/keys",
    )
    app.is_google_auth_configured = False
    app.is_microsoft_auth_configured = False

    if (
        app.config["ENABLE_GOOGLE_AUTH"]
        and app.config["GOOGLE_CLIENT_ID"]
        and app.config["GOOGLE_CLIENT_SECRET"]
    ):
        app.is_google_auth_configured = True

    if (
        app.config["ENABLE_MICROSOFT_AUTH"]
        and app.config["MICROSOFT_CLIENT_ID"]
        and app.config["MICROSOFT_CLIENT_SECRET"]
    ):
        app.is_microsoft_auth_configured = True


def configure_models(app):
    from app import models

    app.models = {
        name: getattr(models, name)
        for name in dir(models)
        if isinstance(getattr(models, name), type)
    }
    app.db = db
    return


def configure_extensions(app):
    db.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    limiter.init_app(app)
    return


def registering_blueprints(app):
    from app.main import main as main_blueprint

    app.register_blueprint(main_blueprint)

    from app.api_v1 import api as api_v1_blueprint

    app.register_blueprint(api_v1_blueprint, url_prefix="/api/v1")

    from app.auth import auth as auth_blueprint

    app.register_blueprint(auth_blueprint)

    # --- Masri blueprints ---
    from app.masri.settings_routes import settings_bp

    app.register_blueprint(settings_bp)

    from app.masri.wisp_routes import wisp_bp

    app.register_blueprint(wisp_bp)

    from app.masri.mcp_server import mcp_bp

    app.register_blueprint(mcp_bp)

    from app.masri.llm_routes import llm_bp

    app.register_blueprint(llm_bp)

    from app.masri.notification_routes import notification_bp

    app.register_blueprint(notification_bp)

    from app.masri.entra_routes import entra_bp
    app.register_blueprint(entra_bp)

    from app.masri.telivy_routes import telivy_bp
    app.register_blueprint(telivy_bp)

    return


def configure_errors(app):
    def handle_error(e, title):
        """Generic error handler for API and HTML responses."""
        if request.path.startswith("/api/"):
            response = (
                e.description
                if isinstance(e.description, dict)
                else {"ok": False, "message": e.description, "code": e.code}
            )
            return jsonify(response), e.code

        return (
            render_template(
                "layouts/errors/default.html", title=title, description=e.description
            ),
            e.code,
        )

    @app.errorhandler(405)
    def invalid_method(e):
        return handle_error(e, "Invalid method")

    @app.errorhandler(422)
    def client_error(e):
        return handle_error(e, "Client: bad request")

    @app.errorhandler(404)
    def not_found(e):
        return handle_error(e, "Not found")

    @app.errorhandler(400)
    def bad_request(e):
        return handle_error(e, "Bad request")

    @app.errorhandler(401)
    def not_authenticated(e):
        return handle_error(e, "Unauthenticated")

    @app.errorhandler(403)
    def not_authorized(e):
        return handle_error(e, "Unauthorized")

    @app.errorhandler(500)
    def internal_error(e):
        return handle_error(e, "Internal error")

    @app.errorhandler(exc.SQLAlchemyError)
    def handle_db_exceptions(e):
        app.logger.warning(f"Database error: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass

        error_str = str(e)
        # Check if it's a missing column error — tell user to run migrations
        if "UndefinedColumn" in error_str or "does not exist" in error_str:
            error = "Database schema needs updating. Restart the app or run: flask db upgrade"
            app.logger.error("Missing DB column detected — run migrations: %s", error_str[:200])
        elif app.debug:
            try:
                error = str(e.orig)
            except Exception:
                error = "Database error occurred"
        else:
            error = "An unexpected error occurred. Please try again."

        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": error, "code": 500}), 500
        return (
            render_template("layouts/errors/default.html", title="Error", description=error),
            500,
        )


def configure_logging(app):
    """Configures logging for Flask with fallback to standard logging if GCP logging fails."""

    # Clear existing handlers to avoid duplicate logs
    app.logger.handlers.clear()

    if app.config.get("ENABLE_GCP_LOGGING", False):
        try:
            from google.cloud import logging as gcloud_logging

            gcloud_client = gcloud_logging.Client()
            gcloud_client.setup_logging()

            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '{"message": "%(message)s", "severity": "%(levelname)s"}'
            )
            handler.setFormatter(formatter)

            app.logger.addHandler(handler)
            app.logger.setLevel(app.config["LOG_LEVEL"])

            app.logger.info("Enabled GCP logging")
            return
        except Exception as e:
            app.logger.error(f"Failed to configure GCP Logging, falling back: {e}")

    # Fallback to Standard Logging
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    app.logger.addHandler(handler)
    app.logger.setLevel(app.config["LOG_LEVEL"])

    app.logger.info("Enabled standard Flask logging")



def configure_security_headers(app):
    """Add security headers to every response."""

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP: allow inline scripts (needed for Alpine.js) but restrict sources
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'self';"
        )
        if not app.debug:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


def set_config_options(app):
    app.is_email_configured = False
    app.is_self_registration_enabled = False

    if app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]:
        app.is_email_configured = True
    if app.config["ENABLE_SELF_REGISTRATION"]:
        app.is_self_registration_enabled = True

    app.config["IS_SELF_REGISTRATION_ENABLED"] = app.is_self_registration_enabled
    app.config["IS_EMAIL_CONFIGURED"] = app.is_email_configured
