"""
Automated Evidence Generators — C1 Implementation

Generates compliance evidence artifacts from cached integration data
(ConfigStore) without calling external APIs. Each generator reads from
the tenant_integration_data_{tenant_id} cache and produces ProjectEvidence
records linked to applicable subcontrols.

Usage (called from _bg_auto_process after LLM phases):
    from app.masri.evidence_generators import generate_all_evidence
    generate_all_evidence(db, project, tenant_id)
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def generate_all_evidence(db, project, tenant_id):
    """Run all integration extractors against cached config data to produce IntegrationFact rows.
    
    (Retains 'project' in signature for backwards compatibility with calling code during rollout).
    """
    from app.models import ConfigStore

    record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
    if not record or not record.value:
        return 0

    try:
        data = json.loads(record.value)
    except (json.JSONDecodeError, TypeError):
        return 0

    total = 0
    microsoft = data.get("microsoft", {})
    telivy = data.get("telivy", {})
    ninjaone = data.get("ninjaone", {})
    defensx = data.get("defensx", {})

    if microsoft:
        total += _extract_microsoft_facts(db, tenant_id, microsoft)
    if telivy:
        total += _extract_telivy_facts(db, tenant_id, telivy)
    if ninjaone:
        total += _extract_ninjaone_facts(db, tenant_id, ninjaone)
    if defensx:
        total += _extract_defensx_facts(db, tenant_id, defensx)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to commit integration facts")
        return 0

    return total


def _create_integration_fact(db, tenant_id, source, subject, assertion):
    """Create an IntegrationFact record if one with the exact fingerprint doesn't exist."""
    from app.models.tenant import IntegrationFact
    import hashlib
    
    fingerprint_input = f"{tenant_id}:{source}:{subject}:{assertion}"
    fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()
    
    existing = db.session.execute(
        db.select(IntegrationFact).filter_by(tenant_id=tenant_id, fingerprint=fingerprint)
    ).scalars().first()
    
    if existing:
        return None
        
    fact = IntegrationFact(
        tenant_id=tenant_id,
        source=source,
        subject=subject,
        assertion=assertion,
        fingerprint=fingerprint
    )
    db.session.add(fact)
    db.session.flush()
    return fact


# ---------------------------------------------------------------------------
# Microsoft Facts
# ---------------------------------------------------------------------------

def _extract_microsoft_facts(db, tenant_id, ms_data):
    total = 0

    # 1. MFA
    users = ms_data.get("users", [])
    mfa_details = ms_data.get("mfa_registration_details", [])
    if users or mfa_details:
        mfa_enrolled = sum(1 for u in mfa_details if u.get("isMfaRegistered")) if mfa_details else 0
        total_users = len(mfa_details) if mfa_details else len(users)
        pct = round(mfa_enrolled / total_users * 100) if total_users else 0
        assertion = json.dumps({"enrolled": mfa_enrolled, "total": total_users, "pct": pct})
        if _create_integration_fact(db, tenant_id, "microsoft", "mfa_enrollment", assertion):
            total += 1

    # 2. Device Compliance
    devices = ms_data.get("managed_devices", [])
    if devices:
        compliant = sum(1 for d in devices if d.get("complianceState") == "compliant")
        encrypted = sum(1 for d in devices if d.get("isEncrypted"))
        assertion = json.dumps({"compliant": compliant, "encrypted": encrypted, "total": len(devices)})
        if _create_integration_fact(db, tenant_id, "microsoft", "device_compliance", assertion):
            total += 1

    # 3. Conditional Access
    ca_policies = ms_data.get("conditional_access_policies", [])
    if ca_policies:
        enabled = len([p for p in ca_policies if p.get("state") == "enabled"])
        assertion = json.dumps({"enabled_policies": enabled, "total_policies": len(ca_policies)})
        if _create_integration_fact(db, tenant_id, "microsoft", "conditional_access", assertion):
            total += 1

    # 4. Secure Score
    secure_scores = ms_data.get("secure_scores", [])
    if secure_scores:
        latest = secure_scores[0] if isinstance(secure_scores, list) else secure_scores
        current = latest.get("currentScore", 0)
        max_score = latest.get("maxScore", 0)
        assertion = json.dumps({"score": current, "max_score": max_score})
        if _create_integration_fact(db, tenant_id, "microsoft", "secure_score", assertion):
            total += 1

    # 5. Security Alerts
    alerts = ms_data.get("security_alerts", [])
    if alerts:
        high_sev = len([a for a in alerts if a.get("severity") in ("high", "critical")])
        assertion = json.dumps({"total_alerts": len(alerts), "high_critical": high_sev})
        if _create_integration_fact(db, tenant_id, "microsoft", "security_alerts", assertion):
            total += 1

    # 6. Sign-in Anomaly
    sign_ins = ms_data.get("sign_in_logs", [])
    risky_users = ms_data.get("risky_users", [])
    if sign_ins or risky_users:
        failed = len([s for s in sign_ins if s.get("status", {}).get("errorCode", 0) != 0]) if sign_ins else 0
        assertion = json.dumps({"failed_sign_ins": failed, "risky_users": len(risky_users)})
        if _create_integration_fact(db, tenant_id, "microsoft", "sign_in_risk", assertion):
            total += 1

    return total


# ---------------------------------------------------------------------------
# Telivy Facts
# ---------------------------------------------------------------------------

def _extract_telivy_facts(db, tenant_id, tv_data):
    total = 0

    # 1. External Vuln
    findings = tv_data.get("findings", [])
    if findings or tv_data.get("scan_info") or tv_data.get("scan"):
        critical = sum(1 for f in findings if f.get("severity") in ("critical", "high"))
        assertion = json.dumps({"critical_high": critical, "total": len(findings)})
        if _create_integration_fact(db, tenant_id, "telivy", "external_scan", assertion):
            total += 1

    # 2. Breach Data
    breach_data = tv_data.get("breach_data", tv_data.get("risk_assessment", {}).get("breaches", []))
    if breach_data:
        items = breach_data if isinstance(breach_data, list) else [breach_data]
        assertion = json.dumps({"breach_records": len(items)})
        if _create_integration_fact(db, tenant_id, "telivy", "breach_exposure", assertion):
            total += 1

    # 3. Email Security
    email_findings = [f for f in findings if any(kw in (f.get("name", "") + f.get("title", "")).lower() for kw in ("spf", "dkim", "dmarc", "email", "mail", "spoofing"))]
    if email_findings:
        assertion = json.dumps({"email_findings": len(email_findings)})
        if _create_integration_fact(db, tenant_id, "telivy", "email_security", assertion):
            total += 1

    return total


# ---------------------------------------------------------------------------
# NinjaOne Facts
# ---------------------------------------------------------------------------

def _extract_ninjaone_facts(db, tenant_id, ninja_data):
    total = 0

    # 1. Patch compliance
    os_patches = ninja_data.get("os_patches", [])
    sw_patches = ninja_data.get("software_patches", [])
    if os_patches or sw_patches:
        pending_os = sum(1 for p in os_patches if p.get("status") in ("MANUAL", "FAILED", "PENDING"))
        pending_sw = sum(1 for p in sw_patches if p.get("status") in ("MANUAL", "FAILED", "PENDING"))
        assertion = json.dumps({"pending_os": pending_os, "pending_sw": pending_sw, "total_os": len(os_patches), "total_sw": len(sw_patches)})
        if _create_integration_fact(db, tenant_id, "ninjaone", "patch_compliance", assertion):
            total += 1

    # 2. AV Status
    av_status = ninja_data.get("antivirus_status", [])
    av_threats = ninja_data.get("antivirus_threats", [])
    if av_status:
        protected = sum(1 for a in av_status if a.get("productState") in ("ON", "on", "enabled"))
        assertion = json.dumps({"av_active": protected, "total_devices": len(av_status), "threats_detected": len(av_threats)})
        if _create_integration_fact(db, tenant_id, "ninjaone", "antivirus_status", assertion):
            total += 1

    # 3. Device Inventory
    devices = ninja_data.get("devices", [])
    if devices:
        assertion = json.dumps({"total_devices": len(devices)})
        if _create_integration_fact(db, tenant_id, "ninjaone", "device_inventory", assertion):
            total += 1

    return total


# ---------------------------------------------------------------------------
# DefensX Facts
# ---------------------------------------------------------------------------

def _extract_defensx_facts(db, tenant_id, dx_data):
    total = 0

    # 1. Web filtering
    web_policies = dx_data.get("web_policies", dx_data.get("policy_compliance", {}))
    if web_policies:
        policies = web_policies if isinstance(web_policies, list) else [web_policies]
        assertion = json.dumps({"policies_tracked": len(policies)})
        if _create_integration_fact(db, tenant_id, "defensx", "web_filtering", assertion):
            total += 1

    # 2. Shadow AI
    shadow_ai = dx_data.get("shadow_ai", dx_data.get("shadow_ai_detection", []))
    if shadow_ai:
        items = shadow_ai if isinstance(shadow_ai, list) else [shadow_ai]
        assertion = json.dumps({"shadow_ai_services": len(items)})
        if _create_integration_fact(db, tenant_id, "defensx", "shadow_ai", assertion):
            total += 1

    return total

