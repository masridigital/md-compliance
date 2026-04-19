"""
Branding service — tenant-scoped visual overrides on top of platform defaults.

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.
"""

from typing import Any, Mapping

from app import db
from app.masri.new_models import TenantBranding
from app.services import platform_service


_ALLOWED_OVERRIDES = frozenset({
    "logo_url",
    "primary_color",
    "subdomain",
    "welcome_message",
    "email_sender_name",
    "report_header_style",
})


def get_tenant_branding(tenant_id: str) -> dict:
    """Return the effective branding dict for ``tenant_id``.

    Starts from the singleton ``PlatformSettings`` (logo, colours, login
    copy, ...) and overlays any non-null fields from the tenant's
    ``TenantBranding`` row. Returns a plain dict — the view serialises
    directly.
    """
    ps = platform_service.get_platform_settings()
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

    tb = db.session.execute(
        db.select(TenantBranding).filter_by(tenant_id=tenant_id)
    ).scalars().first()
    if tb:
        overrides = tb.as_dict()
        for key in _ALLOWED_OVERRIDES:
            if overrides.get(key):
                base[key] = overrides[key]

    return base


def update_tenant_branding(tenant_id: str, data: Mapping[str, Any]) -> TenantBranding:
    """Create or update the ``TenantBranding`` row for ``tenant_id``. Commits.

    Only keys in ``_ALLOWED_OVERRIDES`` are applied.
    """
    tb = db.session.execute(
        db.select(TenantBranding).filter_by(tenant_id=tenant_id)
    ).scalars().first()
    if tb is None:
        tb = TenantBranding(tenant_id=tenant_id)
        db.session.add(tb)

    for key, value in data.items():
        if key in _ALLOWED_OVERRIDES:
            setattr(tb, key, value)
    db.session.commit()
    return tb
