"""
Masri Digital Compliance Platform — Continuous Monitoring Engine

Detects configuration drift by comparing the current integration data
snapshot against a stored baseline.  Runs during each integration
refresh and generates alerts when significant changes are detected.

Drift types detected:
  - Conditional Access policies added/removed/modified
  - MFA disabled for a user
  - New admin role assignments
  - Device compliance policy changes
  - Intune device non-compliance spikes
  - Secure Score drops > 5 points

Usage:
    from app.masri.continuous_monitor import check_drift, create_baseline
    baseline = create_baseline(tenant_id, microsoft_data)
    drift = check_drift(tenant_id, current_data)
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def create_baseline(tenant_id, integration_data):
    """
    Snapshot the current integration data as the known-good baseline.

    Extracts key configuration items from the cached integration data
    and stores them in ConfigStore.

    Args:
        tenant_id: Tenant ID
        integration_data: Dict from ConfigStore("tenant_integration_data_{tid}")

    Returns:
        dict: The baseline snapshot
    """
    from app import db
    from app.models import ConfigStore

    baseline = {
        "created": datetime.utcnow().isoformat(),
        "tenant_id": tenant_id,
    }

    # Extract Microsoft baseline
    ms_data = integration_data.get("microsoft", {})
    if ms_data:
        baseline["microsoft"] = _extract_microsoft_baseline(ms_data)

    # Extract NinjaOne baseline
    ninja_data = integration_data.get("ninjaone", {})
    if ninja_data:
        baseline["ninjaone"] = _extract_ninjaone_baseline(ninja_data)

    # Store baseline
    ConfigStore.upsert(
        f"compliance_baseline_{tenant_id}",
        json.dumps(baseline, default=str)[:5000000],
    )
    db.session.commit()

    logger.info("Created compliance baseline for tenant %s", tenant_id)
    return baseline


def _extract_microsoft_baseline(ms_data):
    """Extract key configuration items from Microsoft data for baseline."""
    baseline = {}

    # Conditional Access policies
    ca_policies = ms_data.get("conditional_access_policies", [])
    baseline["conditional_access"] = {
        "count": len(ca_policies),
        "policies": {
            p.get("id", ""): {
                "name": p.get("displayName", ""),
                "state": p.get("state", ""),
            }
            for p in ca_policies
            if isinstance(p, dict)
        },
    }

    # MFA enrollment state
    users = ms_data.get("users", [])
    mfa_users = ms_data.get("mfa_registration", [])
    mfa_map = {}
    for u in mfa_users:
        if isinstance(u, dict):
            upn = u.get("userPrincipalName", "")
            mfa_map[upn] = u.get("isMfaRegistered", False)

    baseline["mfa_enrollment"] = {
        "total_users": len(users),
        "mfa_registered": sum(1 for v in mfa_map.values() if v),
        "mfa_not_registered": [
            upn for upn, registered in mfa_map.items() if not registered
        ],
    }

    # Admin role holders
    admin_users = []
    for u in users:
        if isinstance(u, dict):
            roles = u.get("assignedRoles", []) or u.get("roles", [])
            if roles:
                admin_users.append({
                    "upn": u.get("userPrincipalName", ""),
                    "roles": roles,
                })
    baseline["admin_users"] = admin_users

    # Secure Score
    secure_scores = ms_data.get("secure_score", [])
    if secure_scores and isinstance(secure_scores, list) and secure_scores:
        latest = secure_scores[0] if isinstance(secure_scores[0], dict) else {}
        baseline["secure_score"] = {
            "current": latest.get("currentScore", 0),
            "max": latest.get("maxScore", 0),
        }

    # Device compliance summary
    devices = ms_data.get("managed_devices", [])
    compliant = sum(
        1 for d in devices
        if isinstance(d, dict) and d.get("complianceState") == "compliant"
    )
    baseline["device_compliance"] = {
        "total": len(devices),
        "compliant": compliant,
        "non_compliant": len(devices) - compliant,
    }

    return baseline


def _extract_ninjaone_baseline(ninja_data):
    """Extract key config items from NinjaOne data for baseline."""
    baseline = {}

    devices = ninja_data.get("devices", [])
    baseline["device_count"] = len(devices)

    # AV status
    av_status = ninja_data.get("antivirus_status", [])
    av_active = sum(
        1 for a in av_status
        if isinstance(a, dict) and a.get("productState", "").lower() in ("on", "active", "enabled")
    )
    baseline["av_coverage"] = {
        "total": len(av_status),
        "active": av_active,
    }

    return baseline


def check_drift(tenant_id, current_data):
    """
    Compare current integration data against the stored baseline.

    Args:
        tenant_id: Tenant ID
        current_data: Current integration data dict

    Returns:
        list[dict]: List of drift alerts, each with:
            - type: drift category
            - severity: critical|high|medium|low
            - title: short description
            - detail: full description
            - timestamp: ISO timestamp
    """
    from app.models import ConfigStore

    record = ConfigStore.find(f"compliance_baseline_{tenant_id}")
    if not record or not record.value:
        logger.debug("No baseline for tenant %s — skipping drift check", tenant_id)
        return []

    try:
        baseline = json.loads(record.value)
    except (json.JSONDecodeError, TypeError):
        return []

    alerts = []
    now = datetime.utcnow().isoformat()

    # Check Microsoft drift
    ms_baseline = baseline.get("microsoft", {})
    ms_current = current_data.get("microsoft", {})
    if ms_baseline and ms_current:
        alerts.extend(_check_microsoft_drift(ms_baseline, ms_current, now))

    # Check NinjaOne drift
    ninja_baseline = baseline.get("ninjaone", {})
    ninja_current = current_data.get("ninjaone", {})
    if ninja_baseline and ninja_current:
        alerts.extend(_check_ninjaone_drift(ninja_baseline, ninja_current, now))

    if alerts:
        _store_drift_alerts(tenant_id, alerts)
        logger.info(
            "Drift detected for tenant %s: %d alert(s)", tenant_id, len(alerts)
        )

    return alerts


def _check_microsoft_drift(baseline, current, timestamp):
    """Check Microsoft-specific drift."""
    alerts = []

    # 1. Conditional Access policy changes
    bl_ca = baseline.get("conditional_access", {})
    cur_ca_policies = current.get("conditional_access_policies", [])
    cur_ca_map = {
        p.get("id", ""): {
            "name": p.get("displayName", ""),
            "state": p.get("state", ""),
        }
        for p in cur_ca_policies
        if isinstance(p, dict)
    }
    bl_ca_map = bl_ca.get("policies", {})

    # Removed policies
    for pid, pinfo in bl_ca_map.items():
        if pid and pid not in cur_ca_map:
            alerts.append({
                "type": "ca_policy_removed",
                "severity": "critical",
                "title": f"Conditional Access policy removed: {pinfo.get('name', pid)}",
                "detail": f"Policy '{pinfo.get('name', pid)}' was present in baseline but is now missing.",
                "timestamp": timestamp,
            })

    # Disabled policies
    for pid, cur_info in cur_ca_map.items():
        bl_info = bl_ca_map.get(pid, {})
        if bl_info.get("state") == "enabled" and cur_info.get("state") != "enabled":
            alerts.append({
                "type": "ca_policy_disabled",
                "severity": "high",
                "title": f"Conditional Access policy disabled: {cur_info.get('name', pid)}",
                "detail": f"Policy '{cur_info.get('name', pid)}' was enabled but is now {cur_info.get('state', 'unknown')}.",
                "timestamp": timestamp,
            })

    # 2. MFA regression (users who had MFA but lost it)
    bl_mfa = baseline.get("mfa_enrollment", {})
    cur_mfa_data = current.get("mfa_registration", [])
    cur_mfa_map = {}
    for u in cur_mfa_data:
        if isinstance(u, dict):
            cur_mfa_map[u.get("userPrincipalName", "")] = u.get("isMfaRegistered", False)

    bl_no_mfa = set(bl_mfa.get("mfa_not_registered", []))
    cur_no_mfa = {upn for upn, reg in cur_mfa_map.items() if not reg}
    new_no_mfa = cur_no_mfa - bl_no_mfa

    if new_no_mfa:
        alerts.append({
            "type": "mfa_regression",
            "severity": "critical",
            "title": f"MFA disabled for {len(new_no_mfa)} user(s)",
            "detail": f"Users who lost MFA enrollment: {', '.join(sorted(new_no_mfa)[:5])}{'...' if len(new_no_mfa) > 5 else ''}",
            "timestamp": timestamp,
        })

    # 3. New admin role assignments
    bl_admins = {a.get("upn", "") for a in baseline.get("admin_users", []) if isinstance(a, dict)}
    cur_users = current.get("users", [])
    cur_admins = set()
    for u in cur_users:
        if isinstance(u, dict):
            roles = u.get("assignedRoles", []) or u.get("roles", [])
            if roles:
                cur_admins.add(u.get("userPrincipalName", ""))

    new_admins = cur_admins - bl_admins
    if new_admins:
        alerts.append({
            "type": "new_admin",
            "severity": "high",
            "title": f"{len(new_admins)} new admin user(s) detected",
            "detail": f"New admins: {', '.join(sorted(new_admins)[:5])}",
            "timestamp": timestamp,
        })

    # 4. Secure Score drop > 5 points
    bl_score = baseline.get("secure_score", {})
    cur_scores = current.get("secure_score", [])
    if bl_score and cur_scores:
        cur_latest = cur_scores[0] if isinstance(cur_scores, list) and cur_scores else {}
        if isinstance(cur_latest, dict):
            bl_val = bl_score.get("current", 0)
            cur_val = cur_latest.get("currentScore", 0)
            if bl_val and cur_val and (bl_val - cur_val) > 5:
                alerts.append({
                    "type": "secure_score_drop",
                    "severity": "high",
                    "title": f"Secure Score dropped by {bl_val - cur_val:.0f} points",
                    "detail": f"Baseline: {bl_val:.0f}, Current: {cur_val:.0f}",
                    "timestamp": timestamp,
                })

    # 5. Device compliance regression
    bl_dev = baseline.get("device_compliance", {})
    cur_devices = current.get("managed_devices", [])
    if bl_dev and cur_devices:
        cur_noncompliant = sum(
            1 for d in cur_devices
            if isinstance(d, dict) and d.get("complianceState") != "compliant"
        )
        bl_noncompliant = bl_dev.get("non_compliant", 0)
        new_noncompliant = cur_noncompliant - bl_noncompliant
        if new_noncompliant > 0:
            alerts.append({
                "type": "device_compliance_regression",
                "severity": "medium" if new_noncompliant < 5 else "high",
                "title": f"{new_noncompliant} new non-compliant device(s)",
                "detail": f"Non-compliant devices increased from {bl_noncompliant} to {cur_noncompliant}.",
                "timestamp": timestamp,
            })

    return alerts


def _check_ninjaone_drift(baseline, current, timestamp):
    """Check NinjaOne-specific drift."""
    alerts = []

    # AV coverage drop
    bl_av = baseline.get("av_coverage", {})
    cur_av = current.get("antivirus_status", [])
    if bl_av and cur_av:
        cur_active = sum(
            1 for a in cur_av
            if isinstance(a, dict) and a.get("productState", "").lower() in ("on", "active", "enabled")
        )
        bl_active = bl_av.get("active", 0)
        if bl_active and cur_active < bl_active:
            alerts.append({
                "type": "av_coverage_drop",
                "severity": "high",
                "title": f"Antivirus coverage dropped: {bl_active} → {cur_active} devices",
                "detail": f"Active AV decreased from {bl_active} to {cur_active} endpoints.",
                "timestamp": timestamp,
            })

    return alerts


def _store_drift_alerts(tenant_id, alerts):
    """Store drift alerts in ConfigStore for UI display."""
    from app import db
    from app.models import ConfigStore

    record = ConfigStore.find(f"drift_alerts_{tenant_id}")
    existing = []
    if record and record.value:
        try:
            existing = json.loads(record.value)
        except (json.JSONDecodeError, TypeError):
            existing = []

    # Append new alerts, cap at 100 most recent
    combined = alerts + existing
    combined = combined[:100]

    ConfigStore.upsert(
        f"drift_alerts_{tenant_id}",
        json.dumps(combined, default=str),
    )
    db.session.commit()


def get_drift_alerts(tenant_id, limit=50):
    """Get stored drift alerts for a tenant."""
    from app.models import ConfigStore

    record = ConfigStore.find(f"drift_alerts_{tenant_id}")
    if not record or not record.value:
        return []

    try:
        alerts = json.loads(record.value)
        return alerts[:limit]
    except (json.JSONDecodeError, TypeError):
        return []


def get_baseline_info(tenant_id):
    """Get baseline metadata for a tenant."""
    from app.models import ConfigStore

    record = ConfigStore.find(f"compliance_baseline_{tenant_id}")
    if not record or not record.value:
        return None

    try:
        baseline = json.loads(record.value)
        return {
            "created": baseline.get("created"),
            "has_microsoft": "microsoft" in baseline,
            "has_ninjaone": "ninjaone" in baseline,
        }
    except (json.JSONDecodeError, TypeError):
        return None
