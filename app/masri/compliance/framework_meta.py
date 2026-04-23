"""Loader for per-framework questionnaire/exemption/deadline metadata.

Data lives as JSON under ``app/files/framework_metadata/<slug>.json`` so
that regulatory updates can be reviewed as plain diffs and distributed
with the codebase. The structure for each file is documented in
``ny_dfs_23nycrr500.json``.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any


_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "files",
    "framework_metadata",
)


@lru_cache(maxsize=32)
def load(slug: str) -> dict[str, Any] | None:
    path = os.path.join(_DIR, f"{slug}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_available() -> list[str]:
    if not os.path.isdir(_DIR):
        return []
    return sorted(
        os.path.splitext(n)[0]
        for n in os.listdir(_DIR)
        if n.endswith(".json")
    )


def exemption_codes(slug: str) -> list[str]:
    meta = load(slug) or {}
    return [e["code"] for e in meta.get("exemptions", [])]


def section(slug: str, section_code: str) -> dict[str, Any] | None:
    meta = load(slug) or {}
    return meta.get("sections", {}).get(section_code)


def scope_waived_by(slug: str, exemption_code: str) -> list[str]:
    """Return the list of section codes this exemption waives.

    ``"*"`` means full exemption — everything is waived except sections
    explicitly marked ``is_exemptable: false`` (which usually means the
    filing obligation itself).
    """
    meta = load(slug) or {}
    for exemption in meta.get("exemptions", []):
        if exemption.get("code") == exemption_code:
            scope = exemption.get("scope_waived", [])
            if scope == "*":
                return ["*"]
            return list(scope)
    return []
