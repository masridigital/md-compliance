"""
SSO service — ``SettingsSSO`` rows (platform-wide + per-tenant).

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.

``tenant_id=None`` denotes the platform-wide fallback SSO config; a
non-null tenant_id scopes the record to a single tenant.
"""

from typing import Any, Mapping, Optional

from app import db
from app.masri.new_models import SettingsSSO


_ALLOWED_FIELDS = frozenset({
    "provider",
    "client_id",
    "discovery_url",
    "enabled",
    "allow_local_fallback",
    "mfa_required",
    "session_timeout_minutes",
})


def get_sso_config(tenant_id: Optional[str] = None) -> Optional[SettingsSSO]:
    """Return the ``SettingsSSO`` row for the given scope (``tenant_id`` or global)."""
    return db.session.execute(
        db.select(SettingsSSO).filter_by(tenant_id=tenant_id)
    ).scalars().first()


def update_sso_config(
    data: Mapping[str, Any], tenant_id: Optional[str] = None
) -> SettingsSSO:
    """Create or update the SSO row for ``tenant_id`` and commit.

    Only allow-listed fields are applied. ``client_secret`` is encrypted
    via :meth:`SettingsSSO.set_client_secret` when supplied.
    """
    sso = db.session.execute(
        db.select(SettingsSSO).filter_by(tenant_id=tenant_id)
    ).scalars().first()
    if sso is None:
        sso = SettingsSSO(tenant_id=tenant_id)
        db.session.add(sso)

    for key, value in data.items():
        if key in _ALLOWED_FIELDS:
            setattr(sso, key, value)

    if "client_secret" in data and data["client_secret"]:
        sso.set_client_secret(data["client_secret"])

    db.session.commit()
    return sso
