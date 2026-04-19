"""
Platform service — singleton platform settings + MCP API key validation.

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.

Scope: the application-wide ``PlatformSettings`` row and MCP OAuth API
key validation. Anything that needs per-tenant branding overrides lives
in :mod:`app.services.branding_service`.
"""

from typing import Any, Mapping, Optional

from app import db
from app.masri.new_models import MCPAPIKey, PlatformSettings


def get_platform_settings() -> PlatformSettings:
    """Return the singleton ``PlatformSettings`` row, creating it on first call.

    The table is expected to have exactly one row. If no row exists (fresh
    install), we insert defaults and commit so subsequent reads see it.
    """
    ps = db.session.execute(db.select(PlatformSettings)).scalars().first()
    if ps is None:
        ps = PlatformSettings()
        db.session.add(ps)
        db.session.commit()
    return ps


def update_platform_settings(data: Mapping[str, Any]) -> PlatformSettings:
    """Apply allow-listed field updates to the singleton and commit.

    Only keys present in ``PlatformSettings.ALLOWED_FIELDS`` are applied —
    anything else is silently ignored. Matches the behaviour views relied
    on before the split.
    """
    ps = get_platform_settings()
    for key, value in data.items():
        if key in PlatformSettings.ALLOWED_FIELDS:
            setattr(ps, key, value)
    db.session.commit()
    return ps


def get_mcp_key(raw_key: str) -> Optional[MCPAPIKey]:
    """Validate a raw MCP API key; return the row or ``None``.

    Delegates to :meth:`MCPAPIKey.validate` which handles hashing,
    ``enabled`` and ``expires_at`` checks. Exposed through the service
    layer so MCP callers don't reach into models directly.
    """
    return MCPAPIKey.validate(raw_key)
