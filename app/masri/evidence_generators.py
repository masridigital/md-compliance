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
    """Run all evidence generators against cached integration data.

    Returns the number of evidence records created.
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
        total += _generate_microsoft_evidence(db, project, microsoft)
    if telivy:
        total += _generate_telivy_evidence(db, project, telivy)
    if ninjaone:
        total += _generate_ninjaone_evidence(db, project, ninjaone)
    if defensx:
        total += _generate_defensx_evidence(db, project, defensx)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to commit evidence records")
        return 0

    return total


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_evidence(db, project, name, description, content, group):
    """Create a ProjectEvidence record if one with the same name doesn't exist."""
    from app.models import ProjectEvidence, EvidenceAssociation

    existing = db.session.execute(
        db.select(ProjectEvidence).filter_by(
            name=name, project_id=project.id)
    ).scalars().first()
    if existing:
        return None

    ev = ProjectEvidence(
        name=name,
        description=description,
        content=content[:5000] if content else "",
        group=group,
        project_id=project.id,
        tenant_id=project.tenant_id,
    )
    db.session.add(ev)
    db.session.flush()
    return ev


def _associate_by_keywords(db, project, evidence, keywords):
    """Link evidence to subcontrols whose name or parent control category matches keywords."""
    from app.models import EvidenceAssociation
    count = 0
    for pc in project.controls.all():
        ctrl = pc.control
        ctrl_name = (ctrl.name if ctrl else "").lower()
        ctrl_cat = (ctrl.category if ctrl else "").lower()
        if any(kw in ctrl_name or kw in ctrl_cat for kw in keywords):
            for sc in pc.subcontrols.all():
                if sc.is_applicable:
                    if not EvidenceAssociation.exists(sc.id, evidence.id):
                        db.session.add(EvidenceAssociation(
                            control_id=sc.id, evidence_id=evidence.id))
                        count += 1
    return count


# ---------------------------------------------------------------------------
# Microsoft 365 Evidence Generators
# ---------------------------------------------------------------------------

def _generate_microsoft_evidence(db, project, ms_data):
    """Generate evidence from Microsoft 365 / Entra ID cached data."""
    total = 0

    # 1. MFA Enrollment Report
    users = ms_data.get("users", [])
    mfa_details = ms_data.get("mfa_registration_details", [])
    if users or mfa_details:
        mfa_enrolled = sum(1 for u in mfa_details if u.get("isMfaRegistered")) if mfa_details else 0
        total_users = len(mfa_details) if mfa_details else len(users)
        pct = round(mfa_enrolled / total_users * 100) if total_users else 0

        lines = [f"MFA Enrollment Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total users: {total_users}",
                 f"MFA enrolled: {mfa_enrolled} ({pct}%)",
                 f"MFA not enrolled: {total_users - mfa_enrolled}",
                 ""]
        if mfa_details:
            not_enrolled = [u.get("userDisplayName", u.get("userPrincipalName", "?"))
                           for u in mfa_details if not u.get("isMfaRegistered")]
            if not_enrolled:
                lines.append("Users without MFA:")
                for name in not_enrolled[:30]:
                    lines.append(f"  - {name}")
                if len(not_enrolled) > 30:
                    lines.append(f"  ... and {len(not_enrolled) - 30} more")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] MFA Enrollment Report",
                              f"Multi-factor authentication enrollment status. {mfa_enrolled}/{total_users} users enrolled ({pct}%).",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["mfa", "multi-factor", "authentication", "access control", "identity"])
            total += 1

    # 2. Device Compliance Report
    devices = ms_data.get("managed_devices", [])
    if devices:
        compliant = sum(1 for d in devices if d.get("complianceState") == "compliant")
        encrypted = sum(1 for d in devices if d.get("isEncrypted"))
        lines = [f"Device Compliance Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total managed devices: {len(devices)}",
                 f"Compliant: {compliant}",
                 f"Non-compliant: {len(devices) - compliant}",
                 f"Encrypted: {encrypted}",
                 ""]
        non_compliant = [d for d in devices if d.get("complianceState") != "compliant"]
        if non_compliant:
            lines.append("Non-compliant devices:")
            for d in non_compliant[:20]:
                lines.append(f"  - {d.get('deviceName', '?')} ({d.get('operatingSystem', '?')}) — {d.get('complianceState', '?')}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Device Compliance Report",
                              f"Intune device compliance status. {compliant}/{len(devices)} compliant, {encrypted} encrypted.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["endpoint", "device", "encryption", "asset", "mobile", "workstation"])
            total += 1

    # 3. Conditional Access Policy Export
    ca_policies = ms_data.get("conditional_access_policies", [])
    if ca_policies:
        enabled = [p for p in ca_policies if p.get("state") == "enabled"]
        lines = [f"Conditional Access Policy Export — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total policies: {len(ca_policies)}",
                 f"Enabled: {len(enabled)}",
                 ""]
        for p in ca_policies:
            state = p.get("state", "unknown")
            lines.append(f"  [{state.upper()}] {p.get('displayName', '?')}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Conditional Access Policies",
                              f"Azure AD Conditional Access policy inventory. {len(enabled)} enabled policies.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["access control", "conditional", "authentication", "authorization", "logical access"])
            total += 1

    # 4. Secure Score Snapshot
    secure_scores = ms_data.get("secure_scores", [])
    if secure_scores:
        latest = secure_scores[0] if isinstance(secure_scores, list) else secure_scores
        current = latest.get("currentScore", 0)
        max_score = latest.get("maxScore", 0)
        pct = round(current / max_score * 100) if max_score else 0

        gaps = latest.get("controlScores", [])
        gap_items = [g for g in gaps if g.get("score", 0) < g.get("maxScore", 0)]

        lines = [f"Microsoft Secure Score Snapshot — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Current score: {current}/{max_score} ({pct}%)",
                 ""]
        if gap_items:
            lines.append(f"Top gaps ({len(gap_items)} controls below max):")
            for g in gap_items[:15]:
                lines.append(f"  - {g.get('controlName', '?')}: {g.get('score', 0)}/{g.get('maxScore', 0)}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Microsoft Secure Score",
                              f"Security posture score: {current}/{max_score} ({pct}%). {len(gap_items)} controls below maximum.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["security", "posture", "monitoring", "risk", "configuration"])
            total += 1

    # 5. Security Alerts Summary
    alerts = ms_data.get("security_alerts", [])
    if alerts:
        high_sev = [a for a in alerts if a.get("severity") in ("high", "critical")]
        lines = [f"Security Alerts Summary — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total alerts: {len(alerts)}",
                 f"High/Critical: {len(high_sev)}",
                 ""]
        for a in alerts[:20]:
            lines.append(f"  [{a.get('severity', '?').upper()}] {a.get('title', '?')} — {a.get('status', '?')}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Security Alerts Summary",
                              f"Defender alerts: {len(alerts)} total, {len(high_sev)} high/critical severity.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["incident", "alert", "monitoring", "detection", "response", "threat"])
            total += 1

    # 6. Sign-in Anomaly Report
    sign_ins = ms_data.get("sign_in_logs", [])
    risky_users = ms_data.get("risky_users", [])
    if sign_ins or risky_users:
        failed = [s for s in sign_ins if s.get("status", {}).get("errorCode", 0) != 0] if sign_ins else []
        lines = [f"Sign-in Activity Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total sign-in events: {len(sign_ins)}",
                 f"Failed sign-ins: {len(failed)}",
                 f"Risky users flagged: {len(risky_users)}",
                 ""]
        if risky_users:
            lines.append("Risky users:")
            for u in risky_users[:15]:
                lines.append(f"  - {u.get('userDisplayName', '?')} — risk: {u.get('riskLevel', '?')}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Sign-in Activity Report",
                              f"Sign-in monitoring: {len(failed)} failures, {len(risky_users)} risky users.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["monitoring", "audit", "log", "sign-in", "anomaly", "access"])
            total += 1

    return total


# ---------------------------------------------------------------------------
# Telivy Evidence Generators
# ---------------------------------------------------------------------------

def _generate_telivy_evidence(db, project, tv_data):
    """Generate evidence from Telivy external scan cached data."""
    total = 0

    # 1. External Vulnerability Scan Report
    findings = tv_data.get("findings", [])
    scan_info = tv_data.get("scan_info", tv_data.get("scan", {}))
    if findings or scan_info:
        critical = sum(1 for f in findings if f.get("severity") in ("critical", "high"))
        lines = [f"External Vulnerability Scan Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total findings: {len(findings)}",
                 f"Critical/High: {critical}",
                 ""]
        for f in findings[:25]:
            lines.append(f"  [{f.get('severity', '?').upper()}] {f.get('name', f.get('title', '?'))}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] External Vulnerability Scan",
                              f"External scan: {len(findings)} findings, {critical} critical/high severity.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["vulnerability", "scan", "penetration", "network", "external", "firewall", "web app"])
            total += 1

    # 2. Breach Data Report
    breach_data = tv_data.get("breach_data", tv_data.get("risk_assessment", {}).get("breaches", []))
    if breach_data:
        items = breach_data if isinstance(breach_data, list) else [breach_data]
        lines = [f"Breach Exposure Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Breach records found: {len(items)}",
                 ""]
        for b in items[:20]:
            if isinstance(b, dict):
                lines.append(f"  - {b.get('source', b.get('name', '?'))}: {b.get('description', '')[:100]}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Breach Exposure Report",
                              f"Dark web / breach monitoring: {len(items)} records found.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["breach", "incident", "data loss", "password", "credential", "dark web"])
            total += 1

    # 3. Email Security (SPF/DKIM/DMARC)
    email_findings = [f for f in findings if any(
        kw in (f.get("name", "") + f.get("title", "")).lower()
        for kw in ("spf", "dkim", "dmarc", "email", "mail", "spoofing")
    )]
    if email_findings:
        lines = [f"Email Security Assessment — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Email-related findings: {len(email_findings)}",
                 ""]
        for f in email_findings:
            lines.append(f"  [{f.get('severity', '?').upper()}] {f.get('name', f.get('title', '?'))}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Email Security Assessment",
                              f"Email security findings: {len(email_findings)} issues (SPF/DKIM/DMARC/spoofing).",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["email", "communication", "spoofing", "phishing"])
            total += 1

    return total


# ---------------------------------------------------------------------------
# NinjaOne Evidence Generators
# ---------------------------------------------------------------------------

def _generate_ninjaone_evidence(db, project, ninja_data):
    """Generate evidence from NinjaOne RMM cached data."""
    total = 0

    # 1. Patch Compliance Report
    os_patches = ninja_data.get("os_patches", [])
    sw_patches = ninja_data.get("software_patches", [])
    if os_patches or sw_patches:
        pending_os = sum(1 for p in os_patches if p.get("status") in ("MANUAL", "FAILED", "PENDING"))
        pending_sw = sum(1 for p in sw_patches if p.get("status") in ("MANUAL", "FAILED", "PENDING"))
        lines = [f"Patch Compliance Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"OS patches tracked: {len(os_patches)} (pending: {pending_os})",
                 f"Software patches tracked: {len(sw_patches)} (pending: {pending_sw})",
                 ""]

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Patch Compliance Report",
                              f"Patch status: {pending_os} OS patches pending, {pending_sw} software patches pending.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["patch", "update", "vulnerability", "maintenance", "software"])
            total += 1

    # 2. Antivirus Status Report
    av_status = ninja_data.get("antivirus_status", [])
    av_threats = ninja_data.get("antivirus_threats", [])
    if av_status:
        protected = sum(1 for a in av_status if a.get("productState") in ("ON", "on", "enabled"))
        lines = [f"Antivirus Status Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Devices with AV: {len(av_status)}",
                 f"AV active: {protected}",
                 f"Threats detected: {len(av_threats)}",
                 ""]
        if av_threats:
            lines.append("Recent threats:")
            for t in av_threats[:15]:
                lines.append(f"  - {t.get('name', '?')} on {t.get('deviceName', '?')}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Antivirus Status Report",
                              f"AV coverage: {protected}/{len(av_status)} devices active. {len(av_threats)} threats detected.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["malware", "antivirus", "anti-virus", "endpoint", "threat", "protection"])
            total += 1

    # 3. Device Inventory
    devices = ninja_data.get("devices", [])
    if devices:
        lines = [f"Endpoint Inventory Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Total managed endpoints: {len(devices)}",
                 ""]
        os_counts = {}
        for d in devices:
            os_name = d.get("os", d.get("operatingSystem", "Unknown"))
            os_counts[os_name] = os_counts.get(os_name, 0) + 1
        for os_name, count in sorted(os_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {os_name}: {count}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Endpoint Inventory",
                              f"Managed endpoint inventory: {len(devices)} devices across {len(os_counts)} OS types.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["asset", "inventory", "device", "endpoint", "hardware"])
            total += 1

    return total


# ---------------------------------------------------------------------------
# DefensX Evidence Generators
# ---------------------------------------------------------------------------

def _generate_defensx_evidence(db, project, dx_data):
    """Generate evidence from DefensX browser security cached data."""
    total = 0

    # 1. Web Filtering Policy Report
    web_policies = dx_data.get("web_policies", dx_data.get("policy_compliance", {}))
    if web_policies:
        policies = web_policies if isinstance(web_policies, list) else [web_policies]
        lines = [f"Web Filtering Policy Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Policies tracked: {len(policies)}",
                 ""]
        for p in policies[:20]:
            if isinstance(p, dict):
                lines.append(f"  - {p.get('name', p.get('policy_name', '?'))}: {p.get('status', 'active')}")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Web Filtering Policy Report",
                              f"Browser security policies: {len(policies)} policies tracked.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["web", "filter", "browser", "internet", "acceptable use"])
            total += 1

    # 2. Shadow AI Detection Report
    shadow_ai = dx_data.get("shadow_ai", dx_data.get("shadow_ai_detection", []))
    if shadow_ai:
        items = shadow_ai if isinstance(shadow_ai, list) else [shadow_ai]
        lines = [f"Shadow AI Detection Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                 f"Shadow AI services detected: {len(items)}",
                 ""]
        for s in items[:20]:
            if isinstance(s, dict):
                lines.append(f"  - {s.get('service', s.get('name', '?'))}: {s.get('users', '?')} users")

        content = "\n".join(lines)
        ev = _create_evidence(db, project,
                              "[Auto] Shadow AI Detection",
                              f"Shadow AI monitoring: {len(items)} unauthorized AI services detected.",
                              content, "auto_evidence")
        if ev:
            _associate_by_keywords(db, project, ev,
                                   ["data loss", "shadow", "unauthorized", "ai", "acceptable use", "classification"])
            total += 1

    return total
