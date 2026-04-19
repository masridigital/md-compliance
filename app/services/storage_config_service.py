"""
Storage config service — ``SettingsStorage`` provider rows.

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.

This module only manages the *configuration* rows. The runtime routing
that picks which provider to use for a given role lives in
:mod:`app.masri.storage_router`.
"""

from typing import Any, Mapping, Optional

from app import db
from app.masri.new_models import SettingsStorage


def get_storage_provider_config(provider: str) -> Optional[dict]:
    """Return the decrypted provider config dict, or ``None`` if not configured."""
    record = db.session.execute(
        db.select(SettingsStorage).filter_by(provider=provider)
    ).scalars().first()
    if record is None:
        return None
    return record.get_config()


def update_storage_provider(
    provider: str, data: Mapping[str, Any]
) -> SettingsStorage:
    """Create or update a provider row and commit.

    ``data`` may carry ``enabled``, ``is_default``, and a nested ``config``
    dict. When ``is_default`` is truthy we demote every other row so there
    is at most one default — matches the pre-split SQL ``UPDATE`` that
    ``SettingsService`` used to run.
    """
    record = db.session.execute(
        db.select(SettingsStorage).filter_by(provider=provider)
    ).scalars().first()
    if record is None:
        record = SettingsStorage(provider=provider)
        db.session.add(record)

    if "enabled" in data:
        record.enabled = data["enabled"]
    if "is_default" in data:
        if data["is_default"]:
            db.session.execute(
                db.update(SettingsStorage)
                .where(SettingsStorage.id != record.id)
                .values(is_default=False)
            )
        record.is_default = data["is_default"]
    if "config" in data and isinstance(data["config"], dict):
        record.save_config(data["config"])

    db.session.commit()
    return record


def get_default_storage_provider() -> Optional[SettingsStorage]:
    """Return the row flagged ``is_default=True``, or ``None``."""
    return db.session.execute(
        db.select(SettingsStorage).filter_by(is_default=True)
    ).scalars().first()
