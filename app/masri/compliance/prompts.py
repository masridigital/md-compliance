"""System + user prompts for every supported document type.

All prompts pass through the model-family adapters downstream
(:mod:`app.masri.prompt_adapters`), so we keep them vendor-agnostic
here and rely on the adapter to tune structure for Claude / DeepSeek /
Llama / etc.
"""

from __future__ import annotations

import json
from typing import Any


BASE_SYSTEM = """\
You are a compliance document specialist with deep expertise in
regulatory requirements for financial services, legal, healthcare, and
professional services firms.

When generating documents:
- Use formal, precise regulatory language.
- Cite specific regulation sections inline (e.g. "23 NYCRR § 500.3",
  "16 CFR § 314.4(b)", "45 CFR § 164.308(a)(1)").
- Fill every section completely — never leave a placeholder in the
  output.
- Use the organization's actual name. Never use generic terms like
  "the Company" if the real name is supplied.
- Tailor depth and controls to the org's size, licenses, and risk
  profile as described in the questionnaire answers.
- Output Markdown with `#`, `##`, `###` headings so the renderer can
  produce a styled .docx. Do not wrap the whole document in a code
  fence.
- Do not add disclaimers, hedges, or preambles — the reader is the
  author of the final document.
"""


NYDFS_POLICY_SYSTEM = BASE_SYSTEM + """\

Target framework: 23 NYCRR Part 500 (New York Department of Financial
Services Cybersecurity Regulation).

Cover every required element under § 500.3(a)–(k):
(a) Information security
(b) Data governance and classification
(c) Asset inventory and device management
(d) Access controls and identity management
(e) Business continuity and disaster recovery
(f) Systems and network security
(g) Systems and network monitoring
(h) Systems and application development and quality assurance
(i) Physical security and environmental controls
(j) Customer data privacy
(k) Vendor and third-party service provider management

End with: Roles and Responsibilities, Review Cadence, Approval Block.
"""


NYDFS_IRP_SYSTEM = BASE_SYSTEM + """\

Target framework: 23 NYCRR § 500.16 Incident Response Plan.

Include all required elements under § 500.16(a)(1)–(8):
(1) Internal response processes
(2) Goals of the plan
(3) Roles, responsibilities, decision authority
(4) External + internal communications
(5) Remediation requirements for identified weaknesses
(6) Documentation and reporting of events
(7) Post-event plan evaluation and revision
(8) § 500.17 72-hour DFS notification requirement — include the
    notification decision matrix and template.

Include: incident classification matrix (Sev 1–4), escalation tree,
evidence preservation steps, regulator notification template.
"""


NYDFS_RISK_ASSESSMENT_SYSTEM = BASE_SYSTEM + """\

Target framework: 23 NYCRR § 500.9 Risk Assessment.

Deliver a full written Risk Assessment: executive summary, scope,
methodology (threat/vulnerability/likelihood/impact), inventory of
Information Systems and Nonpublic Information categories, threat
landscape (include external and insider risks), control effectiveness,
residual risk register with at least 10 named risks prioritized by
composite score, remediation roadmap with owners and target dates, and
sign-off block for the CISO + board.
"""


NYDFS_EXEMPTION_SYSTEM = BASE_SYSTEM + """\

Target framework: 23 NYCRR § 500.19(f) Notice of Exemption.

Produce the internal memorandum that supports the online DFS exemption
filing. Include:
- Organization profile and DFS license type
- Specific exemption codes claimed (e.g. 500.19(a)(1), (a)(2)) with
  supporting data (employee count, NY revenue, total assets — ONLY
  what's in the questionnaire answers)
- Which Part 500 sections still apply under the limited exemption
- Ongoing compliance obligations (§ 500.2, 500.3, 500.4, 500.14,
  500.16, 500.17, 500.19(f))
- Annual refiling reminder (April 15 each year)
- Senior-officer attestation block
"""


NYDFS_VENDOR_SYSTEM = BASE_SYSTEM + """\

Target framework: 23 NYCRR § 500.11 Third Party Service Provider
Security Policy.

Include: identification/categorization of TPSPs, due diligence
requirements, minimum security requirements in contracts, periodic
assessment cadence, access control + MFA expectations, breach
notification SLA, termination procedures, and an appendix listing
vendor tiers + required controls by tier.
"""


FTC_WISP_SYSTEM = BASE_SYSTEM + """\

Target framework: FTC Safeguards Rule (16 CFR Part 314).

Deliver the full Written Information Security Program covering all 9
required elements under § 314.4:
(a) Qualified Individual designation
(b) Risk Assessment methodology and summary
(c) Safeguards: access controls, encryption, MFA, secure disposal,
    change management, monitoring, training, incident response
(d) Regular testing (pen tests, vuln scans, continuous monitoring)
(e) Personnel security training
(f) Service provider oversight
(g) Written program evaluation and adjustment cadence
(h) Written Incident Response Plan
(i) Annual written report from the Qualified Individual to the board
"""


HIPAA_RISK_SYSTEM = BASE_SYSTEM + """\

Target framework: HIPAA Security Rule (45 CFR §§ 164.308–164.316).

Deliver a full Security Risk Analysis covering 164.308(a)(1)(ii)(A).
Address administrative, physical, and technical safeguards. Produce an
inventory of ePHI systems and data flows, a threat library keyed to
HIPAA, vulnerability assessment, likelihood/impact scoring, and a
prioritized remediation plan referencing the specific implementation
specifications.
"""


EDIT_SUFFIX = """\

You are editing an existing template. Preserve the structure, headings,
and any well-drafted prose. Fill every remaining placeholder (written
as {{NAME}} in the input) with content specific to the organization,
and enhance any section that is clearly incomplete or generic. Do not
delete or restructure sections unless they are redundant or incorrect.
"""


_SYSTEM_PROMPTS: dict[tuple[str, str | None], str] = {
    ("cybersecurity_policy", "ny_dfs_23nycrr500"): NYDFS_POLICY_SYSTEM,
    ("incident_response_plan", "ny_dfs_23nycrr500"): NYDFS_IRP_SYSTEM,
    ("risk_assessment", "ny_dfs_23nycrr500"): NYDFS_RISK_ASSESSMENT_SYSTEM,
    ("nydfs_exemption_notice", "ny_dfs_23nycrr500"): NYDFS_EXEMPTION_SYSTEM,
    ("vendor_management_policy", "ny_dfs_23nycrr500"): NYDFS_VENDOR_SYSTEM,
    ("ftc_wisp", "ftc_safeguards_core"): FTC_WISP_SYSTEM,
    ("hipaa_risk_analysis", "hipaa_v2"): HIPAA_RISK_SYSTEM,
}


_TITLE_BY_TYPE: dict[str, str] = {
    "cybersecurity_policy": "Cybersecurity Policy",
    "incident_response_plan": "Incident Response Plan",
    "risk_assessment": "Risk Assessment Report",
    "nydfs_exemption_notice": "NY DFS Part 500 Exemption Notice",
    "vendor_management_policy": "Third Party Service Provider Security Policy",
    "ftc_wisp": "Written Information Security Program",
    "hipaa_risk_analysis": "HIPAA Security Risk Analysis",
    "access_control_policy": "Access Control Policy",
    "mfa_policy": "Multi-Factor Authentication Policy",
    "encryption_policy": "Encryption Policy",
    "data_retention_policy": "Data Retention Policy",
    "business_continuity_plan": "Business Continuity Plan",
}


def get_system_prompt(doc_type: str, framework_slug: str | None) -> str:
    return _SYSTEM_PROMPTS.get(
        (doc_type, framework_slug),
        BASE_SYSTEM
        + f"\n\nDocument type requested: {doc_type}. Produce a complete, audit-ready document.",
    )


def get_edit_prompt(doc_type: str, framework_slug: str | None) -> str:
    return get_system_prompt(doc_type, framework_slug) + "\n" + EDIT_SUFFIX


def default_title(doc_type: str, org_profile: dict[str, Any]) -> str:
    base = _TITLE_BY_TYPE.get(doc_type, doc_type.replace("_", " ").title())
    org_name = (org_profile or {}).get("name")
    if org_name:
        return f"{org_name} — {base}"
    return base


def build_user_prompt(
    *,
    doc_type: str,
    framework_slug: str | None,
    org_profile: dict[str, Any],
    answers: dict[str, Any],
    exemption_profile: dict[str, Any] | None,
) -> str:
    parts = [
        f"Generate a complete {doc_type.replace('_', ' ')}.",
        "",
        "Organization profile:",
        json.dumps(org_profile or {}, indent=2, default=str),
        "",
        "Questionnaire answers:",
        json.dumps(answers or {}, indent=2, default=str),
    ]
    if exemption_profile:
        parts += [
            "",
            "Exemption profile (apply these waivers where relevant):",
            json.dumps(exemption_profile, indent=2, default=str),
        ]
    parts += [
        "",
        "Output the full document in Markdown, with headings and bullet lists where appropriate.",
    ]
    return "\n".join(parts)


def build_edit_user_prompt(
    *,
    doc_type: str,
    framework_slug: str | None,
    org_profile: dict[str, Any],
    answers: dict[str, Any],
    exemption_profile: dict[str, Any] | None,
    template_text: str,
    unmapped: list[str],
) -> str:
    parts = [
        f"Complete and enhance the following {doc_type.replace('_', ' ')} template.",
        "",
        "Organization profile:",
        json.dumps(org_profile or {}, indent=2, default=str),
        "",
        "Questionnaire answers:",
        json.dumps(answers or {}, indent=2, default=str),
    ]
    if exemption_profile:
        parts += [
            "",
            "Exemption profile:",
            json.dumps(exemption_profile, indent=2, default=str),
        ]
    if unmapped:
        parts += [
            "",
            "Placeholders the mapping left for you to fill contextually:",
            ", ".join(f"{{{{ {p} }}}}" for p in unmapped),
        ]
    parts += [
        "",
        "Template content:",
        "```",
        template_text,
        "```",
        "",
        "Return the completed document as Markdown.",
    ]
    return "\n".join(parts)
