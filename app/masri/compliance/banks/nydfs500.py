"""NY DFS 23 NYCRR Part 500 — questionnaire bank.

Questions drive the exemption determination under § 500.19 and the
applicability assessment for every other section.
"""

from app.masri.compliance.engine import Question, QuestionOption as Opt


QUESTIONS: list[Question] = [
    Question(
        key="legal_name",
        type="text",
        label="Legal name of the organization",
    ),
    Question(
        key="license_type",
        type="single_select",
        label="DFS license type",
        help_text="Select the license under which the organization operates.",
        options=[
            Opt("insurance_company", "Insurance company"),
            Opt("bank", "Bank or trust company"),
            Opt("money_transmitter", "Money transmitter"),
            Opt("title_agent", "Title insurance agent"),
            Opt("mortgage_banker", "Mortgage banker"),
            Opt("mortgage_broker", "Mortgage broker"),
            Opt("mortgage_servicer", "Mortgage servicer"),
            Opt("licensed_lender", "Licensed lender"),
            Opt("virtual_currency", "Virtual currency licensee (BitLicense)"),
            Opt("charter_credit_union", "Charter credit union"),
            Opt("other", "Other DFS licensee"),
        ],
    ),
    Question(
        key="is_captive_insurance",
        type="yes_no",
        label="Is the organization a captive insurance company that does not directly write insurance in New York?",
        help_text="Captive insurance companies meeting this definition qualify for a full exemption under § 500.19(b).",
    ),
    Question(
        key="covered_by_other_dfs_entity",
        type="yes_no",
        label="Is the organization covered under another DFS-licensed entity's cybersecurity program (e.g. parent/affiliate)?",
        help_text="Full exemption under § 500.19(e) if yes.",
    ),
    Question(
        key="employee_count",
        type="number",
        label="Total employees (including independent contractors and affiliates)",
        help_text="§ 500.19(a)(1) — under 20 qualifies for limited exemption.",
        minimum=0,
    ),
    Question(
        key="avg_ny_revenue",
        type="number",
        label="Average gross annual revenue from NY business over the last 3 fiscal years (USD)",
        help_text="§ 500.19(a)(2) — under $7.5M qualifies for limited exemption.",
        minimum=0,
    ),
    Question(
        key="total_assets",
        type="number",
        label="Year-end total assets, including affiliates (USD)",
        help_text="§ 500.19(a)(3) — under $15M qualifies for limited exemption.",
        minimum=0,
    ),
    Question(
        key="operates_information_systems",
        type="yes_no",
        label="Does the organization operate, maintain, utilize, or control any Information Systems?",
    ),
    Question(
        key="holds_npi",
        type="yes_no",
        label="Does the organization hold any Nonpublic Information (NPI)?",
    ),
    Question(
        key="only_encrypted_npi_no_keys",
        type="yes_no",
        label="Is all NPI stored only in encrypted form, with no internal access to the encryption keys?",
        help_text="§ 500.19(d) — qualifies for limited exemption (waives encryption/data-retention/training sections).",
        condition=lambda a: bool(a.get("holds_npi")) is True,
    ),
    Question(
        key="ciso_status",
        type="single_select",
        label="CISO designation",
        help_text="§ 500.4 — every non-exempt Covered Entity must designate a Chief Information Security Officer.",
        options=[
            Opt("internal", "Dedicated internal CISO"),
            Opt("dual_role", "Employee with dual responsibilities"),
            Opt("vciso", "Third-party virtual CISO"),
            Opt("none", "No CISO designated yet"),
        ],
    ),
    Question(
        key="has_written_policy",
        type="yes_no",
        label="Does the organization currently have a written cybersecurity policy approved by senior leadership?",
    ),
    Question(
        key="last_security_training",
        type="single_select",
        label="When was the last security awareness training conducted for all personnel?",
        options=[
            Opt("under_6m", "Within the last 6 months"),
            Opt("6_12m", "6 to 12 months ago"),
            Opt("over_12m", "Over 12 months ago"),
            Opt("never", "Never conducted"),
        ],
    ),
    Question(
        key="has_incident_response_plan",
        type="yes_no",
        label="Does the organization have a written incident response plan covering the items in § 500.16?",
    ),
    Question(
        key="has_board_reporting",
        type="yes_no",
        label="Does the CISO report to the Board (or equivalent governing body) at least annually on program status?",
        condition=lambda a: a.get("ciso_status") != "none",
    ),
    Question(
        key="fiscal_year_end",
        type="date",
        label="Fiscal year-end date",
        help_text="Used to calculate the April 15 annual certification / exemption filing deadline.",
        required=False,
    ),
]
