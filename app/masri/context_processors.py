"""
Masri Digital Compliance Platform — Context Processors

Injects template-global variables into every Jinja2 render context:
  - ``branding`` — merged dict of platform defaults + tenant overrides
  - ``current_tenant`` — active tenant object (if any)

Register in ``create_app()``::

    from app.masri.context_processors import register_context_processors
    register_context_processors(app)
"""

import logging
from flask import session
from flask_login import current_user

logger = logging.getLogger(__name__)


def register_context_processors(app):
    """Attach all Masri context processors to the Flask app."""

    @app.context_processor
    def inject_branding():
        """
        Provide ``branding`` dict to every template.

        Merge order (later wins):
          1. Hard-coded safe defaults
          2. ``app.config`` values (from ``MASRI_CONFIG``)
          3. Database ``TenantBranding`` overrides (if tenant is active)

        Tenant branding is cached in the session for 5 minutes to avoid
        per-request database queries.
        """
        # --- Safe defaults ---
        branding = {
            "app_name": app.config.get("APP_NAME", "Masri Digital"),
            "logo_url": app.config.get("APP_LOGO_URL", "/static/img/logo.svg"),
            "favicon_url": app.config.get("APP_FAVICON_URL", "/static/img/favicon.ico"),
            "primary_color": app.config.get("APP_PRIMARY_COLOR", "#0066CC"),
            "hover_color": _darken_hex(app.config.get("APP_PRIMARY_COLOR", "#0066CC"), 15),
            "light_color": _lighten_hex(app.config.get("APP_PRIMARY_COLOR", "#0066CC"), 90),
            "login_headline": "",
            "login_subheadline": "",
            "login_bg_color": "#F5F5F7",
            "support_email": app.config.get("SUPPORT_EMAIL", "inquiry@masridigital.com"),
        }

        # --- Tenant-level overrides (session-cached) ---
        try:
            tenant_id = _get_active_tenant_id()
            if tenant_id:
                import time
                cache_key = f"_branding_{tenant_id}"
                cached = session.get(cache_key)
                cache_ts = session.get(f"{cache_key}_ts", 0)
                if cached and (time.time() - cache_ts) < 300:
                    tb = cached
                else:
                    from app.masri.settings_service import SettingsService
                    tb = SettingsService.get_tenant_branding(tenant_id)
                    session[cache_key] = tb if isinstance(tb, dict) else {}
                    session[f"{cache_key}_ts"] = time.time()
                if tb:
                    for key in ("app_name", "logo_url", "favicon_url",
                                "primary_color", "hover_color", "light_color",
                                "login_headline", "login_subheadline", "login_bg_color"):
                        val = tb.get(key) if isinstance(tb, dict) else getattr(tb, key, None)
                        if val:
                            branding[key] = val
        except Exception:
            logger.debug("Could not load tenant branding, using defaults", exc_info=True)

        # Platform-level support_email (cached on app object — once per worker)
        if not hasattr(app, "_cached_support_email"):
            try:
                from app.masri.new_models import PlatformSettings
                from app import db
                ps = db.session.execute(db.select(PlatformSettings)).scalars().first()
                app._cached_support_email = ps.support_email if ps and ps.support_email else ""
            except Exception:
                app._cached_support_email = ""
        if app._cached_support_email:
            branding["support_email"] = app._cached_support_email

        return {"branding": branding}

    @app.context_processor
    def inject_current_tenant():
        """
        Provide ``current_tenant`` and ``tenants`` to every template.

        Uses ``db.session.get()`` which hits SQLAlchemy's identity map first,
        avoiding a DB round-trip when the tenant was already loaded this request.
        """
        tenants = []
        current_tenant = None
        try:
            if current_user and current_user.is_authenticated:
                from app import db
                from app.models import Tenant
                user_tenants = getattr(current_user, "tenants", [])
                if user_tenants:
                    tenants = user_tenants
                    tenant_id = _get_active_tenant_id()
                    if tenant_id:
                        # db.session.get() uses identity map — no query if
                        # the tenant was already loaded in this request cycle.
                        current_tenant = db.session.get(Tenant, tenant_id)
                    if not current_tenant and tenants:
                        current_tenant = tenants[0] if hasattr(tenants[0], "id") else None
        except Exception:
            logger.debug("Could not load tenant context", exc_info=True)

        return {
            "current_tenant": current_tenant,
            "tenants": tenants,
        }

    @app.context_processor
    def inject_config_flags():
        """Expose selected config flags to templates.

        NOTE: Do NOT override ``config`` — Flask already injects its
        full config object as ``config``.  Use a separate key instead.
        LLM check is cached on the app object to avoid a DB query per render.
        """
        if not hasattr(app, "_cached_llm_enabled"):
            app._cached_llm_enabled = app.config.get("LLM_ENABLED", False) or _check_llm_db()
        return {
            "feature_flags": {
                "LLM_ENABLED": app._cached_llm_enabled,
                "WISP_ENABLED": app.config.get("WISP_ENABLED", True),
                "MCP_ENABLED": app.config.get("MCP_ENABLED", False),
            }
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_llm_db():
    """Check if LLM is configured in the database (not just env var)."""
    try:
        from app.masri.llm_service import LLMService
        return LLMService.is_enabled()
    except Exception:
        return False


def _get_active_tenant_id():
    """Get the active tenant ID from session or current_user."""
    tid = session.get("active_tenant_id")
    if not tid and current_user and current_user.is_authenticated:
        tid = getattr(current_user, "default_tenant_id", None)
    return tid


def _darken_hex(hex_color: str, percent: int) -> str:
    """Darken a hex color by ``percent`` (0-100)."""
    try:
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        factor = 1 - (percent / 100)
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def _lighten_hex(hex_color: str, percent: int) -> str:
    """Lighten a hex color by ``percent`` (0-100)."""
    try:
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        factor = percent / 100
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color
