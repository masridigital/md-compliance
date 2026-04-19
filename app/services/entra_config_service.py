"""
Entra config service — platform-wide Microsoft Entra ID credentials.

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.

Stores a single platform-level row (``tenant_id=None``). Credentials are
Fernet-encrypted at rest via ``SettingsEntra.set_credentials``.
"""

from typing import Optional

from app import db
from app.masri.new_models import SettingsEntra


def get_entra_config() -> Optional[dict]:
    """Return decrypted credentials dict, or ``None`` if not fully configured.

    Only returns a dict when:
      * a platform-level row exists (``tenant_id=None``),
      * ``enabled=True``,
      * all three fields (tenant id, client id, client secret) are set.

    Callers can treat ``None`` as "fall back to env vars".
    """
    record = db.session.execute(
        db.select(SettingsEntra).filter_by(enabled=True, tenant_id=None)
    ).scalars().first()

    if record is None or not record.is_fully_configured():
        return None

    return record.get_credentials()


def update_entra_config(
    entra_tenant_id: str, client_id: str, client_secret: str
) -> SettingsEntra:
    """Create or update the platform-level Entra credential row and commit.

    All three values are Fernet-encrypted before persistence. Pass an
    empty string for ``client_secret`` to leave the stored secret
    untouched — matches the pre-split semantics that UI forms depend on.
    """
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
