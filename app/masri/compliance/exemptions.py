"""Exemption determination for every supported framework.

Pure functions. Given a framework slug + answers dict, returns the
applicable exemption profile: type (none|limited|full), specific
exemption codes claimed, and the union of section codes those exemptions
waive.

No DB I/O — this layer is unit-testable in isolation.
"""

from __future__ import annotations

from typing import Any

from app.masri.compliance import framework_meta


def determine(
    framework_slug: str, answers: dict[str, Any]
) -> dict[str, Any]:
    """Entry point. Routes to a per-framework determinator."""
    if framework_slug == "ny_dfs_23nycrr500":
        return _determine_nydfs(answers)
    if framework_slug == "ftc_safeguards_core":
        return _determine_ftc(answers)
    return _empty()


# ── NY DFS § 500.19 ───────────────────────────────────────────────────────

def _determine_nydfs(answers: dict[str, Any]) -> dict[str, Any]:
    # Full exemptions are mutually exclusive and short-circuit.
    if _truthy(answers.get("is_captive_insurance")):
        return _compile("ny_dfs_23nycrr500", "full", ["500.19(b)"])
    if _truthy(answers.get("covered_by_other_dfs_entity")):
        return _compile("ny_dfs_23nycrr500", "full", ["500.19(e)"])

    claimed: list[str] = []
    if _num(answers.get("employee_count"), default=None, threshold=20, op="lt"):
        claimed.append("500.19(a)(1)")
    if _num(answers.get("avg_ny_revenue"), default=None, threshold=7_500_000, op="lt"):
        claimed.append("500.19(a)(2)")
    if _num(answers.get("total_assets"), default=None, threshold=15_000_000, op="lt"):
        claimed.append("500.19(a)(3)")
    # 500.19(c) requires BOTH conditions: no info systems and no NPI
    if not _truthy(answers.get("operates_information_systems")) and not _truthy(
        answers.get("holds_npi")
    ):
        claimed.append("500.19(c)")
    if _truthy(answers.get("only_encrypted_npi_no_keys")):
        claimed.append("500.19(d)")

    if not claimed:
        return _compile("ny_dfs_23nycrr500", "none", [])
    return _compile("ny_dfs_23nycrr500", "limited", claimed)


# ── FTC Safeguards Rule § 314.6(a) ─────────────────────────────────────────

def _determine_ftc(answers: dict[str, Any]) -> dict[str, Any]:
    claimed: list[str] = []
    if _num(answers.get("consumer_records"), default=None, threshold=5000, op="lt"):
        claimed.append("314.6(a)")
    if claimed:
        return _compile("ftc_safeguards_core", "limited", claimed)
    return _compile("ftc_safeguards_core", "none", [])


# ── Helpers ────────────────────────────────────────────────────────────────

def _compile(
    framework_slug: str, kind: str, codes: list[str]
) -> dict[str, Any]:
    scope: set[str] = set()
    for code in codes:
        waived = framework_meta.scope_waived_by(framework_slug, code)
        if waived == ["*"]:
            scope = {"*"}
            break
        scope.update(waived)
    return {
        "exemption_type": kind,
        "exemptions_claimed": {c: True for c in codes},
        "scope_waived": sorted(scope) if "*" not in scope else ["*"],
        "rationale": _rationale(framework_slug, codes),
    }


def _empty() -> dict[str, Any]:
    return {
        "exemption_type": "none",
        "exemptions_claimed": {},
        "scope_waived": [],
        "rationale": "",
    }


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "y", "1")
    return bool(value)


def _num(
    value: Any,
    *,
    default: Any,
    threshold: float,
    op: str = "lt",
) -> bool:
    """Return True when the numeric value satisfies the threshold comparison.

    Unanswered numeric questions (``None``) return False — we only claim an
    exemption when the operator has actually confirmed eligibility.
    """
    if value in (None, "", default):
        return False
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return False
    if op == "lt":
        return fval < threshold
    if op == "le":
        return fval <= threshold
    if op == "gt":
        return fval > threshold
    if op == "ge":
        return fval >= threshold
    return False


def _rationale(framework_slug: str, codes: list[str]) -> str:
    if not codes:
        return "No exemptions claimed — organization is a fully Covered Entity."
    meta = framework_meta.load(framework_slug) or {}
    by_code = {e["code"]: e for e in meta.get("exemptions", [])}
    lines = []
    for code in codes:
        ex = by_code.get(code, {})
        lines.append(f"- {code}: {ex.get('label', '')}")
    return (
        "Exemptions claimed based on questionnaire answers:\n" + "\n".join(lines)
    )


# ── Applicability helpers used by compliance-score + gap analysis ──────────

def applicable_sections(
    framework_slug: str,
    exemption_profile_dict: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Partition a framework's sections into {applicable, exempt}.

    Pass either a fresh :func:`determine` result or an ``ExemptionProfile``
    ``as_dict()``.
    """
    meta = framework_meta.load(framework_slug) or {}
    all_sections: list[str] = list((meta.get("sections") or {}).keys())

    waived = set((exemption_profile_dict or {}).get("scope_waived") or [])
    full = "*" in waived

    applicable: list[str] = []
    exempt: list[str] = []
    for code in all_sections:
        section = meta["sections"][code]
        if not section.get("is_exemptable", False):
            # Sections that cannot be waived stay applicable even under a
            # full exemption — e.g. the exemption filing itself.
            applicable.append(code)
            continue
        if full or code in waived:
            exempt.append(code)
        else:
            applicable.append(code)
    return {"applicable": applicable, "exempt": exempt}
