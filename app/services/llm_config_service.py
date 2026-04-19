"""
LLM config service — primary ``SettingsLLM`` row management.

Split out of ``SettingsService`` during Phase E3. See :mod:`app.services`
for conventions.

The platform treats ``SettingsLLM`` as a singleton (one primary
provider); additional providers live in
``ConfigStore("llm_additional_providers")`` and are managed elsewhere.
"""

from typing import Any, List, Mapping, Optional

from app import db
from app.masri.new_models import SettingsLLM


_ALLOWED_FIELDS = frozenset({
    "provider",
    "model_name",
    "azure_endpoint",
    "azure_deployment",
    "enabled",
    "token_budget_per_tenant",
    "rate_limit_per_hour",
})


def get_active_llm_config() -> Optional[SettingsLLM]:
    """Return the first enabled ``SettingsLLM`` row, or ``None`` if unset."""
    return db.session.execute(
        db.select(SettingsLLM).filter_by(enabled=True)
    ).scalars().first()


def get_all_llm_configs() -> List[SettingsLLM]:
    """Return every ``SettingsLLM`` row (enabled or not)."""
    return list(db.session.execute(db.select(SettingsLLM)).scalars().all())


def update_llm_config(data: Mapping[str, Any]) -> SettingsLLM:
    """Create or update the primary ``SettingsLLM`` row and commit.

    Only allow-listed fields are applied. A non-empty ``api_key`` entry
    is routed through :meth:`SettingsLLM.set_api_key` so the key is
    Fernet-encrypted before persistence.
    """
    llm = db.session.execute(db.select(SettingsLLM)).scalars().first()
    if llm is None:
        llm = SettingsLLM()
        db.session.add(llm)

    for key, value in data.items():
        if key in _ALLOWED_FIELDS:
            setattr(llm, key, value)

    if "api_key" in data and data["api_key"]:
        llm.set_api_key(data["api_key"])

    db.session.commit()
    return llm
