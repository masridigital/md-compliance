"""
Masri Digital Compliance Platform — Telivy CSRA → Compliance Framework Mapper

Translates Telivy security assessment data into compliance control evidence
and status updates across multiple frameworks:

  Frameworks supported:
    - NIST CSF (nist_csf)
    - NIST SP 800-53 (nist_800_53)
    - ISO/IEC 27001:2022 (iso27001)
    - CIS Controls v8 (cis_v8)
    - SOC 2 Trust Services Criteria (soc2)
    - HIPAA Security Rule (hipaa)
    - CMMC Level 1/2 (cmmc)

Mapping strategy (three layers):
  1. CATEGORY MAPPING  — Telivy executive-summary categories (networkSecurity,
     identityAccessManagement, …) → relevant control ref_codes per framework.
  2. FINDING SLUG MAPPING — individual Telivy finding slugs → specific controls.
  3. CIS AUTO-MAP — FindingWithTaskResponseDTO.cisCategory is passed through
     directly when the target project uses the CIS framework.

Grade → implementation status:
  A  →  3  (fully implemented)
  B  →  2  (largely implemented)
  C  →  1  (partially implemented)
  D  →  1  (partially implemented)
  F  →  0  (not implemented)
  n/a → None (skip — control not applicable)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grade → implementation integer (ProjectSubControl.implemented)
# ---------------------------------------------------------------------------

GRADE_TO_IMPLEMENTED = {
    "A": 3,
    "B": 2,
    "C": 1,
    "D": 1,
    "F": 0,
    "n/a": None,  # None → skip, don't update
}

GRADE_TO_RISK_LEVEL = {
    "A": "low",
    "B": "low",
    "C": "moderate",
    "D": "high",
    "F": "critical",
    "n/a": "unknown",
}

SEVERITY_TO_RISK = {
    "high": "high",
    "medium": "moderate",
    "low": "low",
    "info": "low",
}

# ---------------------------------------------------------------------------
# Category → framework control ref_codes
#
# Keys match Telivy ExecutiveSummaryDTO + SecurityGradesDTO field names.
# Values are dicts keyed by the platform's framework name string.
# Ref codes follow each framework's canonical numbering.
# ---------------------------------------------------------------------------

CATEGORY_CONTROLS: dict[str, dict[str, list[str]]] = {

    # ── Social Engineering / Phishing / Email Security ─────────────────────
    "socialEngineering": {
        "nist_csf":    ["PR.AT-1", "PR.AT-2", "DE.AE-2", "RS.CO-2"],
        "nist_800_53": ["AT-2", "AT-3", "SI-3", "RA-3"],
        "iso27001":    ["A.7.2.2", "A.12.2.1", "A.13.2.3"],
        "cis_v8":      ["CIS-9", "CIS-14"],
        "soc2":        ["CC1.4", "CC2.2", "CC9.2"],
        "hipaa":       ["164.308(a)(5)(ii)(A)", "164.308(a)(5)(ii)(B)"],
        "cmmc":        ["AT.L1-3.2.1", "AT.L2-3.2.2"],
    },

    # ── Network Security / Firewall / VPN / Open Ports ─────────────────────
    "networkSecurity": {
        "nist_csf":    ["PR.AC-5", "PR.DS-5", "DE.CM-1", "PR.PT-4"],
        "nist_800_53": ["SC-7", "SC-8", "SC-10", "CM-7", "AC-4"],
        "iso27001":    ["A.13.1.1", "A.13.1.2", "A.13.1.3", "A.12.6.1"],
        "cis_v8":      ["CIS-4", "CIS-12", "CIS-13"],
        "soc2":        ["CC6.6", "CC7.1", "A1.1", "A1.2"],
        "hipaa":       ["164.312(e)(1)", "164.312(e)(2)(ii)", "164.308(a)(1)(ii)(A)"],
        "cmmc":        ["SC.L1-3.13.1", "SC.L2-3.13.2", "SC.L2-3.13.5"],
    },

    # ── Application Security / CVEs / Web Vulnerabilities ──────────────────
    "applicationSecurity": {
        "nist_csf":    ["PR.IP-2", "DE.CM-8", "RS.MI-3", "ID.RA-1"],
        "nist_800_53": ["SA-11", "SA-15", "SI-2", "SI-10", "RA-5"],
        "iso27001":    ["A.14.1.1", "A.14.2.1", "A.14.2.8", "A.12.6.1"],
        "cis_v8":      ["CIS-7", "CIS-16"],
        "soc2":        ["CC7.1", "CC8.1", "CC3.2"],
        "hipaa":       ["164.312(c)(1)", "164.308(a)(8)"],
        "cmmc":        ["SI.L1-3.14.1", "SI.L2-3.14.3", "CA.L2-3.12.3"],
    },

    # ── DNS Health / SPF / DKIM / DMARC ────────────────────────────────────
    "dnsHealth": {
        "nist_csf":    ["PR.DS-2", "DE.CM-1", "PR.AC-5"],
        "nist_800_53": ["SC-20", "SC-21", "SC-22", "SI-3"],
        "iso27001":    ["A.13.1.1", "A.13.2.1", "A.12.2.1"],
        "cis_v8":      ["CIS-4", "CIS-9", "CIS-12"],
        "soc2":        ["CC6.6", "CC7.1"],
        "hipaa":       ["164.312(e)(1)", "164.312(e)(2)(i)"],
        "cmmc":        ["SC.L1-3.13.1", "SI.L1-3.14.1"],
    },

    # ── IP Reputation / Blacklisting ───────────────────────────────────────
    "ipReputation": {
        "nist_csf":    ["ID.RA-1", "DE.CM-1", "DE.AE-1"],
        "nist_800_53": ["RA-3", "SI-3", "SI-4"],
        "iso27001":    ["A.12.4.1", "A.12.6.1", "A.16.1.4"],
        "cis_v8":      ["CIS-7", "CIS-13"],
        "soc2":        ["CC3.2", "CC7.2"],
        "hipaa":       ["164.308(a)(1)(ii)(D)", "164.308(a)(6)"],
        "cmmc":        ["RA.L2-3.11.1", "SI.L2-3.14.3"],
    },

    # ── External Vulnerabilities / Attack Surface ───────────────────────────
    "externalVulnerabilities": {
        "nist_csf":    ["ID.RA-1", "ID.RA-5", "DE.CM-8", "PR.IP-12"],
        "nist_800_53": ["RA-5", "CA-8", "SI-2", "SA-11"],
        "iso27001":    ["A.12.6.1", "A.14.2.8", "A.18.2.3"],
        "cis_v8":      ["CIS-7", "CIS-18"],
        "soc2":        ["CC3.2", "CC7.1", "CC4.1"],
        "hipaa":       ["164.308(a)(1)(ii)(A)", "164.308(a)(8)"],
        "cmmc":        ["RA.L2-3.11.2", "CA.L2-3.12.1", "CA.L2-3.12.3"],
    },

    # ── Data Security / Encryption / DLP ───────────────────────────────────
    "dataSecurity": {
        "nist_csf":    ["PR.DS-1", "PR.DS-2", "PR.DS-5", "PR.DS-6"],
        "nist_800_53": ["SC-28", "SC-8", "MP-2", "MP-4", "SC-13"],
        "iso27001":    ["A.10.1.1", "A.10.1.2", "A.18.1.3", "A.8.2.3"],
        "cis_v8":      ["CIS-3"],
        "soc2":        ["C1.1", "C1.2", "CC6.7"],
        "hipaa":       ["164.312(a)(2)(iv)", "164.312(e)(2)(ii)", "164.312(c)(1)"],
        "cmmc":        ["MP.L1-3.8.1", "MP.L2-3.8.3", "SC.L2-3.13.16"],
    },

    # ── Identity & Access Management / MFA / Passwords ─────────────────────
    "identityAccessManagement": {
        "nist_csf":    ["PR.AC-1", "PR.AC-6", "PR.AC-7", "PR.AC-4"],
        "nist_800_53": ["AC-2", "AC-3", "IA-2", "IA-5", "IA-8"],
        "iso27001":    ["A.9.1.1", "A.9.2.1", "A.9.2.4", "A.9.4.2", "A.9.4.3"],
        "cis_v8":      ["CIS-5", "CIS-6"],
        "soc2":        ["CC6.1", "CC6.2", "CC6.3"],
        "hipaa":       ["164.312(a)(1)", "164.312(a)(2)(i)", "164.312(a)(2)(iii)", "164.312(d)"],
        "cmmc":        ["AC.L1-3.1.1", "AC.L1-3.1.2", "IA.L1-3.5.1", "IA.L1-3.5.2"],
    },

    # ── Dark Web / Breach Presence ──────────────────────────────────────────
    "darkWebPresence": {
        "nist_csf":    ["DE.AE-1", "DE.AE-2", "RS.AN-1", "ID.RA-2"],
        "nist_800_53": ["IR-6", "SI-4", "RA-3"],
        "iso27001":    ["A.16.1.1", "A.16.1.2", "A.12.4.1"],
        "cis_v8":      ["CIS-17"],
        "soc2":        ["CC3.2", "CC7.3", "CC9.1"],
        "hipaa":       ["164.308(a)(6)(i)", "164.308(a)(6)(ii)"],
        "cmmc":        ["IR.L2-3.6.1", "IR.L2-3.6.2"],
    },

    # ── Microsoft 365 Security ──────────────────────────────────────────────
    "m365Security": {
        "nist_csf":    ["PR.AC-1", "PR.AC-7", "PR.AT-1", "PR.DS-2"],
        "nist_800_53": ["AC-2", "IA-2", "IA-5", "SC-8", "SI-3"],
        "iso27001":    ["A.9.2.1", "A.9.4.2", "A.12.2.1", "A.13.2.3"],
        "cis_v8":      ["CIS-4", "CIS-5", "CIS-9"],
        "soc2":        ["CC6.1", "CC6.6", "CC6.7"],
        "hipaa":       ["164.312(a)(1)", "164.312(e)(1)", "164.308(a)(5)(ii)(B)"],
        "cmmc":        ["AC.L1-3.1.1", "IA.L1-3.5.1", "SI.L1-3.14.1"],
    },

    # ── Google Workspace Security ───────────────────────────────────────────
    "gwsSecurity": {
        "nist_csf":    ["PR.AC-1", "PR.AC-7", "PR.AT-1", "PR.DS-2"],
        "nist_800_53": ["AC-2", "IA-2", "IA-5", "SC-8", "SI-3"],
        "iso27001":    ["A.9.2.1", "A.9.4.2", "A.12.2.1", "A.13.2.3"],
        "cis_v8":      ["CIS-4", "CIS-5", "CIS-9"],
        "soc2":        ["CC6.1", "CC6.6", "CC6.7"],
        "hipaa":       ["164.312(a)(1)", "164.312(e)(1)", "164.308(a)(5)(ii)(B)"],
        "cmmc":        ["AC.L1-3.1.1", "IA.L1-3.5.1", "SI.L1-3.14.1"],
    },
}

# ---------------------------------------------------------------------------
# Finding slug → framework control ref_codes
#
# Common Telivy finding slugs mapped to specific controls.
# This supplements the category mapping with more precise per-finding links.
# ---------------------------------------------------------------------------

SLUG_CONTROLS: dict[str, dict[str, list[str]]] = {
    # Email / Social Engineering
    "TYPO_SQUATTING":          {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-20"], "iso27001": ["A.13.1.1"], "cis_v8": ["CIS-9"], "soc2": ["CC6.6"]},
    "PERSONAL_EMAILS":         {"nist_csf": ["PR.AC-1"], "nist_800_53": ["AC-2"],  "iso27001": ["A.9.2.1"],  "cis_v8": ["CIS-5"], "soc2": ["CC6.1"]},
    "SPF_MISSING":             {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-20"], "iso27001": ["A.13.2.3"], "cis_v8": ["CIS-9"], "soc2": ["CC6.6"]},
    "DKIM_MISSING":            {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-20"], "iso27001": ["A.13.2.3"], "cis_v8": ["CIS-9"], "soc2": ["CC6.6"]},
    "DMARC_MISSING":           {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-20"], "iso27001": ["A.13.2.3"], "cis_v8": ["CIS-9"], "soc2": ["CC6.6"]},
    "DMARC_NOT_ENFORCED":      {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-20"], "iso27001": ["A.13.2.3"], "cis_v8": ["CIS-9"], "soc2": ["CC6.6"]},
    "MX_RECORD_EXPOSED":       {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-20"], "iso27001": ["A.13.1.1"], "cis_v8": ["CIS-12"],"soc2": ["CC6.6"]},

    # Network
    "OPEN_PORTS":              {"nist_csf": ["PR.AC-5", "PR.PT-4"], "nist_800_53": ["SC-7", "CM-7"], "iso27001": ["A.13.1.1"], "cis_v8": ["CIS-4", "CIS-12"], "soc2": ["CC6.6"]},
    "INSECURE_SSL":            {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-8"],  "iso27001": ["A.10.1.1", "A.13.1.1"], "cis_v8": ["CIS-3"], "soc2": ["CC6.7"]},
    "EXPIRED_SSL":             {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-8"],  "iso27001": ["A.10.1.1"], "cis_v8": ["CIS-3"], "soc2": ["CC6.7"]},
    "WEAK_CIPHER":             {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-8", "SC-13"], "iso27001": ["A.10.1.1"], "cis_v8": ["CIS-3"], "soc2": ["CC6.7"]},
    "HTTP_NOT_REDIRECTED":     {"nist_csf": ["PR.DS-2"], "nist_800_53": ["SC-8"],  "iso27001": ["A.13.1.1"], "cis_v8": ["CIS-4"], "soc2": ["CC6.6"]},

    # Vulnerabilities
    "CVE_DETECTED":            {"nist_csf": ["ID.RA-1", "DE.CM-8"], "nist_800_53": ["RA-5", "SI-2"], "iso27001": ["A.12.6.1"], "cis_v8": ["CIS-7"], "soc2": ["CC3.2", "CC7.1"]},
    "OUTDATED_SOFTWARE":       {"nist_csf": ["PR.IP-12", "DE.CM-8"], "nist_800_53": ["SI-2"],        "iso27001": ["A.12.6.1"], "cis_v8": ["CIS-7"], "soc2": ["CC7.1"]},

    # Disk / Data Security
    "DISK_NOT_ENCRYPTED":      {"nist_csf": ["PR.DS-1"], "nist_800_53": ["SC-28", "MP-4"], "iso27001": ["A.10.1.1", "A.8.2.3"], "cis_v8": ["CIS-3"], "soc2": ["C1.1"], "hipaa": ["164.312(a)(2)(iv)"]},
    "BROWSER_PASSWORD":        {"nist_csf": ["PR.AC-7"], "nist_800_53": ["IA-5"],           "iso27001": ["A.9.4.3"],             "cis_v8": ["CIS-5"], "soc2": ["CC6.1"]},

    # Dark Web / Breach
    "EMAIL_BREACH":            {"nist_csf": ["DE.AE-1", "RS.AN-1"], "nist_800_53": ["IR-6", "SI-4"], "iso27001": ["A.16.1.1"], "cis_v8": ["CIS-17"], "soc2": ["CC7.3"]},
    "PASSWORD_BREACH":         {"nist_csf": ["PR.AC-7", "DE.AE-1"], "nist_800_53": ["IA-5", "IR-6"], "iso27001": ["A.9.4.3"],  "cis_v8": ["CIS-5", "CIS-17"], "soc2": ["CC6.1", "CC7.3"]},

    # IP reputation
    "IP_BLACKLISTED":          {"nist_csf": ["DE.AE-1", "ID.RA-1"], "nist_800_53": ["RA-3", "SI-4"], "iso27001": ["A.12.4.1"], "cis_v8": ["CIS-7", "CIS-13"], "soc2": ["CC7.2"]},
}

# ---------------------------------------------------------------------------
# Public mapping API
# ---------------------------------------------------------------------------

def grade_to_implemented(grade: Optional[str]) -> Optional[int]:
    """Convert a Telivy letter grade to a ProjectSubControl.implemented integer."""
    if grade is None:
        return None
    return GRADE_TO_IMPLEMENTED.get(grade.upper())


def grade_to_risk(grade: Optional[str]) -> str:
    """Convert a Telivy letter grade to a RiskRegister.risk string."""
    if grade is None:
        return "unknown"
    return GRADE_TO_RISK_LEVEL.get(grade.upper(), "unknown")


def severity_to_risk(severity: Optional[str]) -> str:
    """Convert a Telivy finding severity to RiskRegister.risk."""
    if severity is None:
        return "unknown"
    return SEVERITY_TO_RISK.get(severity.lower(), "unknown")


def get_controls_for_category(
    category: str,
    framework: str,
) -> list[str]:
    """
    Return the list of control ref_codes for a Telivy category + framework.

    Args:
        category:  Telivy category name (e.g. "networkSecurity")
        framework: Platform framework name (e.g. "nist_csf", "iso27001")

    Returns:
        List of ref_code strings (may be empty if no mapping exists).
    """
    return CATEGORY_CONTROLS.get(category, {}).get(framework, [])


def get_controls_for_slug(
    slug: str,
    framework: str,
) -> list[str]:
    """
    Return control ref_codes for a specific Telivy finding slug + framework.
    """
    return SLUG_CONTROLS.get(slug, {}).get(framework, [])


def map_executive_summary(
    executive_summary: dict,
    framework: str,
) -> list[dict]:
    """
    Map Telivy ExecutiveSummaryDTO to a list of control-update dicts.

    Each item contains:
      {
        "ref_codes":   [...],     # control ref_codes to match
        "implemented": 0-3|None,  # new implemented value
        "grade":       "A"|...,
        "category":    "networkSecurity"|...,
        "summary":     "...",     # executive summary text
      }

    Args:
        executive_summary: dict from RiskAssessmentDTO.executiveSummary
        framework:         target framework name

    Returns:
        List of mapping dicts (one per category that has a grade).
    """
    mappings = []

    for category, score_obj in executive_summary.items():
        if not isinstance(score_obj, dict):
            continue

        grade = score_obj.get("securityScore")
        summary_text = score_obj.get("summary", "")
        implemented = grade_to_implemented(grade)

        ref_codes = get_controls_for_category(category, framework)
        if not ref_codes:
            continue

        mappings.append({
            "category":    category,
            "grade":       grade,
            "implemented": implemented,
            "ref_codes":   ref_codes,
            "summary":     summary_text,
        })

    return mappings


def map_grades(grades: dict, framework: str) -> list[dict]:
    """
    Map Telivy SecurityGradesDTO (from ExternalScanDTO) to control-update dicts.

    Similar to map_executive_summary but uses the simpler grades structure.
    """
    mappings = []

    for category, grade in grades.items():
        if grade is None:
            continue

        implemented = grade_to_implemented(grade)
        ref_codes = get_controls_for_category(category, framework)
        if not ref_codes:
            continue

        mappings.append({
            "category":    category,
            "grade":       grade,
            "implemented": implemented,
            "ref_codes":   ref_codes,
            "summary":     f"Telivy {category} grade: {grade}",
        })

    return mappings


def map_findings_to_controls(
    findings: list[dict],
    framework: str,
) -> list[dict]:
    """
    Map Telivy SecurityFindingDTO list to per-finding control refs.

    Each item contains:
      {
        "slug":        "CVE_DETECTED",
        "name":        "CVE Detected",
        "severity":    "high",
        "risk_level":  "high",
        "ref_codes":   [...],
        "description": "...",
        "recommendation": "...",
        "scan_type":   "...",
        "cis_category": "..." | None,   # from FindingWithTaskResponseDTO
        "control_id":   "..." | None,
      }
    """
    result = []

    for finding in findings:
        slug = finding.get("slug", "")
        severity = finding.get("severity", "info")
        cis_category = finding.get("cisCategory")
        control_id = finding.get("controlId")

        # Slug-level mapping first; fall back to scan-type category
        ref_codes = get_controls_for_slug(slug, framework)

        # If the finding carries a CIS category and we're on cis_v8, use it
        if not ref_codes and framework == "cis_v8" and cis_category:
            ref_codes = [cis_category]

        if not ref_codes:
            continue

        result.append({
            "slug":           slug,
            "name":           finding.get("name", slug),
            "severity":       severity,
            "risk_level":     severity_to_risk(severity),
            "ref_codes":      ref_codes,
            "description":    finding.get("description", ""),
            "recommendation": finding.get("recommendation", ""),
            "scan_type":      finding.get("scanType", ""),
            "cis_category":   cis_category,
            "control_id":     control_id,
        })

    return result


def build_evidence_content(
    assessment_type: str,
    assessment_id: str,
    organization: str,
    domain: str,
    category_mappings: list[dict],
    finding_mappings: list[dict],
) -> str:
    """
    Build a JSON-serialisable string for ProjectEvidence.content
    summarising the Telivy CSRA sync.
    """
    import json
    from datetime import datetime

    payload = {
        "source":          "telivy",
        "assessment_type": assessment_type,
        "assessment_id":   assessment_id,
        "organization":    organization,
        "domain":          domain,
        "synced_at":       datetime.utcnow().isoformat(),
        "category_grades": [
            {
                "category":    m["category"],
                "grade":       m["grade"],
                "ref_codes":   m["ref_codes"],
                "summary":     m["summary"],
            }
            for m in category_mappings
        ],
        "finding_slugs": [
            {
                "slug":           m["slug"],
                "name":           m["name"],
                "severity":       m["severity"],
                "recommendation": m["recommendation"],
                "ref_codes":      m["ref_codes"],
            }
            for m in finding_mappings
        ],
    }
    return json.dumps(payload, indent=2)


def supported_frameworks() -> list[str]:
    """Return the list of framework names this mapper supports."""
    first_category = next(iter(CATEGORY_CONTROLS.values()))
    return sorted(first_category.keys())
