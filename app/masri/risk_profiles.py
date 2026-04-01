"""
Masri Digital Compliance Platform — User & Device Risk Profile Engine

Computes composite risk scores (0-100) for each user and device in a tenant
based on data from Microsoft Entra ID, Intune, Defender, and Telivy.

Risk profiles are stored in ConfigStore per tenant and displayed on the
project Risk Profiles tab. LLM Tier 4 generates narratives for high-risk items.

Usage::

    from app.masri.risk_profiles import compute_risk_profiles
    profiles = compute_risk_profiles(microsoft_data)
    # profiles = {"users": [...], "devices": [...], "summary": {...}}
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring weights — tune these to adjust risk sensitivity
# ---------------------------------------------------------------------------

USER_WEIGHTS = {
    "no_mfa": 30,           # No MFA enrolled
    "risky_flagged": 25,    # Flagged by Identity Protection
    "risky_high": 40,       # High risk level from Identity Protection
    "failed_signins": 10,   # Excessive failed sign-ins (>5 in 7 days)
    "unusual_location": 8,  # Sign-in from unusual location
    "stale_account": 10,    # No activity in 30+ days
    "disabled_account": 5,  # Account disabled but still exists
    "admin_multiplier": 1.5,  # Admin accounts get 1.5x weight
    "non_compliant_device": 15,  # Has non-compliant assigned device
    "shared_mailbox": -20,  # Shared mailboxes get reduced risk (not interactive)
}

DEVICE_WEIGHTS = {
    "non_compliant": 35,    # Not meeting compliance policy
    "unencrypted": 30,      # No disk encryption
    "outdated_os": 15,      # OS version behind
    "stale_sync": 12,       # No sync in 14+ days
    "no_antivirus": 20,     # No AV detected (placeholder — not all APIs expose this)
    "server_multiplier": 1.3,  # Servers get 1.3x weight (higher value target)
    "risky_user_device": 10,  # Assigned to a high-risk user
}


def compute_risk_profiles(microsoft_data):
    """Compute risk profiles for all users and devices from Microsoft data.

    Args:
        microsoft_data: dict from EntraIntegration.collect_all_security_data()
            Expected keys: users, mfa, devices, risky_users, risk_detections,
            sign_in_summary, compliance, secure_score

    Returns:
        dict with:
            users: list of user risk profile dicts (sorted by score desc)
            devices: list of device risk profile dicts (sorted by score desc)
            summary: aggregate stats
    """
    user_profiles = _compute_user_profiles(microsoft_data)
    device_profiles = _compute_device_profiles(microsoft_data)

    # Cross-link: if a user is high-risk, their devices inherit risk
    high_risk_users = {u["upn"] for u in user_profiles if u["score"] >= 60}
    for d in device_profiles:
        if d.get("user") in high_risk_users:
            d["risk_factors"].append("Assigned to high-risk user")
            d["score"] = min(100, d["score"] + DEVICE_WEIGHTS["risky_user_device"])

    # Re-sort after cross-linking
    device_profiles.sort(key=lambda x: x["score"], reverse=True)

    # Summary
    total_users = len(user_profiles)
    total_devices = len(device_profiles)
    high_risk_users_count = sum(1 for u in user_profiles if u["score"] >= 60)
    high_risk_devices_count = sum(1 for d in device_profiles if d["score"] >= 60)
    avg_user_score = round(sum(u["score"] for u in user_profiles) / total_users, 1) if total_users else 0
    avg_device_score = round(sum(d["score"] for d in device_profiles) / total_devices, 1) if total_devices else 0

    return {
        "users": user_profiles,
        "devices": device_profiles,
        "summary": {
            "total_users": total_users,
            "total_devices": total_devices,
            "high_risk_users": high_risk_users_count,
            "high_risk_devices": high_risk_devices_count,
            "avg_user_score": avg_user_score,
            "avg_device_score": avg_device_score,
            "computed_at": datetime.utcnow().isoformat(),
        },
    }


def _compute_user_profiles(data):
    """Score each user based on MFA, risk signals, sign-in activity, devices."""
    profiles = []

    # Build lookup tables
    users_list = data.get("users", {})
    if isinstance(users_list, dict):
        users_list = users_list.get("sample", [])

    mfa_list = data.get("mfa", [])
    mfa_map = {}
    if isinstance(mfa_list, list):
        for m in mfa_list:
            upn = m.get("user_id") or m.get("display_name", "")
            mfa_map[upn] = m

    risky_users = data.get("risky_users", [])
    risky_map = {u.get("upn", ""): u for u in risky_users if isinstance(u, dict)}

    risk_detections = data.get("risk_detections", [])
    detection_map = {}
    for d in risk_detections:
        upn = d.get("user_principal_name", "")
        detection_map.setdefault(upn, []).append(d)

    # Device compliance per user
    devices = data.get("devices", {})
    non_compliant_by_user = {}
    if isinstance(devices, dict):
        for d in devices.get("non_compliant_devices", []):
            user = d.get("user", "")
            if user:
                non_compliant_by_user.setdefault(user, []).append(d)

    # Process each user
    all_users = []
    # Merge users from multiple sources
    seen_upns = set()
    for u in users_list:
        upn = u.get("email") or u.get("userPrincipalName") or u.get("id", "")
        if upn and upn not in seen_upns:
            seen_upns.add(upn)
            all_users.append({
                "display_name": u.get("display_name", u.get("displayName", upn)),
                "upn": upn,
                "account_enabled": u.get("account_enabled", True),
                "created": u.get("created"),
            })

    # Also add users from MFA list that aren't in users_list
    for m in mfa_list:
        dn = m.get("display_name", "")
        uid = m.get("user_id", "")
        key = uid or dn
        if key and key not in seen_upns:
            seen_upns.add(key)
            all_users.append({
                "display_name": dn,
                "upn": key,
                "account_enabled": True,
            })

    for user in all_users:
        score = 0
        factors = []
        upn = user["upn"]
        display_name = user["display_name"]

        # MFA check
        mfa_info = mfa_map.get(upn) or mfa_map.get(display_name)
        if mfa_info:
            if not mfa_info.get("mfa_registered"):
                score += USER_WEIGHTS["no_mfa"]
                factors.append("No MFA enrolled")
            is_admin = mfa_info.get("is_admin", False)
        else:
            # No MFA data = assume not enrolled
            score += USER_WEIGHTS["no_mfa"]
            factors.append("MFA status unknown")
            is_admin = False

        # Identity Protection risk
        risky = risky_map.get(upn)
        if risky:
            risk_level = risky.get("risk_level", "").lower()
            if risk_level == "high":
                score += USER_WEIGHTS["risky_high"]
                factors.append(f"High risk: {risky.get('risk_detail', 'flagged')}")
            elif risk_level in ("medium", "low"):
                score += USER_WEIGHTS["risky_flagged"]
                factors.append(f"Risk flagged: {risk_level}")

        # Risk detections
        detections = detection_map.get(upn, [])
        for det in detections[:3]:
            score += 5
            factors.append(f"Risk detection: {det.get('risk_type', 'unknown')} from {det.get('ip_address', '?')}")

        # Non-compliant devices
        nc_devices = non_compliant_by_user.get(upn, [])
        if nc_devices:
            score += USER_WEIGHTS["non_compliant_device"] * min(len(nc_devices), 3)
            factors.append(f"{len(nc_devices)} non-compliant device(s)")

        # Disabled account
        if not user.get("account_enabled", True):
            score += USER_WEIGHTS["disabled_account"]
            factors.append("Account disabled")

        # Admin multiplier
        if is_admin:
            score = int(score * USER_WEIGHTS["admin_multiplier"])
            factors.append("Admin account (1.5x risk weight)")

        # Determine if shared mailbox (heuristic: name contains "shared" or "#")
        name_lower = (display_name or "").lower()
        is_shared = any(kw in name_lower for kw in ("shared", "noreply", "info@", "admin@", "support@"))
        user_type = "shared_mailbox" if is_shared else "licensed_user"
        if is_shared:
            score = max(0, score + USER_WEIGHTS["shared_mailbox"])

        # Cap at 100
        score = min(100, max(0, score))

        # Risk level
        if score >= 70:
            risk_level = "critical"
        elif score >= 50:
            risk_level = "high"
        elif score >= 25:
            risk_level = "medium"
        else:
            risk_level = "low"

        profiles.append({
            "display_name": display_name,
            "upn": upn,
            "score": score,
            "risk_level": risk_level,
            "type": user_type,
            "risk_factors": factors,
            "mfa_enrolled": bool(mfa_info and mfa_info.get("mfa_registered")),
            "is_admin": is_admin,
            "account_enabled": user.get("account_enabled", True),
        })

    profiles.sort(key=lambda x: x["score"], reverse=True)
    return profiles


def _compute_device_profiles(data):
    """Score each device based on compliance, encryption, OS, sync status."""
    profiles = []

    devices = data.get("devices", {})
    if not isinstance(devices, dict):
        return profiles

    all_devices = []
    # Get from the full device list if available
    for d in devices.get("non_compliant_devices", []):
        all_devices.append(d)
    # Also include compliant devices if we have them
    # The summary might not include compliant device details, so we work with what we have

    # Build from raw managed devices if available
    raw_devices = data.get("_raw_devices", [])
    if raw_devices:
        all_devices = raw_devices

    # If we only have summary stats, create synthetic entries
    if not all_devices and devices.get("total_devices"):
        # We have counts but not individual devices — score at aggregate level
        return [{
            "name": "Fleet Average",
            "score": max(0, 100 - int(devices.get("compliance_rate", 100))),
            "risk_level": "high" if devices.get("compliance_rate", 100) < 70 else "medium" if devices.get("compliance_rate", 100) < 90 else "low",
            "type": "aggregate",
            "risk_factors": [
                f"{devices.get('non_compliant', 0)} non-compliant devices",
                f"{devices.get('unencrypted', 0)} unencrypted devices",
                f"Compliance rate: {devices.get('compliance_rate', 0)}%",
                f"Encryption rate: {devices.get('encryption_rate', 0)}%",
            ],
            "os": "Mixed",
            "user": "Multiple",
            "compliance": f"{devices.get('compliance_rate', 0)}%",
            "encrypted": f"{devices.get('encryption_rate', 0)}%",
        }]

    seen = set()
    for d in all_devices:
        name = d.get("name") or d.get("deviceName") or d.get("id", "unknown")
        if name in seen:
            continue
        seen.add(name)

        score = 0
        factors = []

        # Compliance
        compliance = (d.get("compliance") or d.get("complianceState") or "").lower()
        if compliance in ("noncompliant", "non_compliant"):
            score += DEVICE_WEIGHTS["non_compliant"]
            factors.append("Non-compliant with policy")
        elif compliance not in ("compliant",):
            score += 10
            factors.append(f"Compliance unknown: {compliance}")

        # Encryption
        encrypted = d.get("encrypted") or d.get("isEncrypted")
        if encrypted is False:
            score += DEVICE_WEIGHTS["unencrypted"]
            factors.append("Disk not encrypted")
        elif encrypted is None:
            score += 5
            factors.append("Encryption status unknown")

        # Last sync
        last_sync = d.get("last_sync") or d.get("lastSyncDateTime")
        if last_sync:
            try:
                sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00")).replace(tzinfo=None)
                days_since = (datetime.utcnow() - sync_dt).days
                if days_since > 30:
                    score += DEVICE_WEIGHTS["stale_sync"] + 5
                    factors.append(f"Last sync {days_since} days ago (stale)")
                elif days_since > 14:
                    score += DEVICE_WEIGHTS["stale_sync"]
                    factors.append(f"Last sync {days_since} days ago")
            except Exception:
                pass

        # OS check (basic — could be enhanced with version DB)
        os_name = (d.get("os") or d.get("operatingSystem") or "").lower()
        is_server = "server" in os_name or "linux" in os_name
        if is_server:
            score = int(score * DEVICE_WEIGHTS["server_multiplier"])
            factors.append("Server (1.3x risk weight)")

        # Cap
        score = min(100, max(0, score))

        if score >= 70:
            risk_level = "critical"
        elif score >= 50:
            risk_level = "high"
        elif score >= 25:
            risk_level = "medium"
        else:
            risk_level = "low"

        profiles.append({
            "name": name,
            "score": score,
            "risk_level": risk_level,
            "type": "server" if is_server else "endpoint",
            "risk_factors": factors,
            "os": d.get("os") or d.get("operatingSystem") or "Unknown",
            "os_version": d.get("os_version") or d.get("osVersion") or "",
            "user": d.get("user") or d.get("userPrincipalName") or "Unassigned",
            "compliance": compliance,
            "encrypted": encrypted,
            "model": d.get("model") or "",
            "last_sync": last_sync,
        })

    profiles.sort(key=lambda x: x["score"], reverse=True)
    return profiles
