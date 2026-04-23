"""FTC Safeguards Rule (16 CFR Part 314) — questionnaire bank."""

from app.masri.compliance.engine import Question, QuestionOption as Opt


QUESTIONS: list[Question] = [
    Question(
        key="legal_name",
        type="text",
        label="Legal name of the financial institution",
    ),
    Question(
        key="institution_type",
        type="single_select",
        label="Financial institution type",
        options=[
            Opt("tax_preparer", "Tax preparer / CPA firm"),
            Opt("mortgage_broker", "Mortgage broker or lender"),
            Opt("auto_dealer", "Automobile dealer (credit sales)"),
            Opt("debt_collector", "Debt collector"),
            Opt("investment_advisor", "Registered investment advisor"),
            Opt("check_casher", "Check casher / payday lender"),
            Opt("other_financial", "Other non-bank financial institution"),
        ],
    ),
    Question(
        key="consumer_records",
        type="number",
        label="Number of consumer records collected or maintained",
        help_text="§ 314.6(a) — fewer than 5,000 qualifies for the small-entity exemption.",
        minimum=0,
    ),
    Question(
        key="has_qi_designation",
        type="yes_no",
        label="Has a Qualified Individual been designated to oversee the information security program?",
    ),
    Question(
        key="last_risk_assessment",
        type="single_select",
        label="When was the last written risk assessment completed?",
        options=[
            Opt("under_12m", "Within the last 12 months"),
            Opt("12_24m", "12 to 24 months ago"),
            Opt("over_24m", "Over 24 months ago"),
            Opt("never", "Never"),
        ],
    ),
    Question(
        key="has_written_wisp",
        type="yes_no",
        label="Does the organization have a Written Information Security Program (WISP)?",
    ),
    Question(
        key="has_incident_response",
        type="yes_no",
        label="Is there a written incident response plan covering § 314.4(h)?",
    ),
    Question(
        key="has_mfa",
        type="single_select",
        label="Is multi-factor authentication enforced for all customer-data access?",
        options=[
            Opt("yes_all", "Yes — on all systems"),
            Opt("partial", "Partial — on some systems"),
            Opt("no", "No"),
        ],
    ),
    Question(
        key="encrypts_customer_data",
        type="single_select",
        label="Is customer data encrypted in transit and at rest?",
        options=[
            Opt("both", "Both in transit and at rest"),
            Opt("transit_only", "In transit only"),
            Opt("rest_only", "At rest only"),
            Opt("neither", "Neither"),
        ],
    ),
    Question(
        key="vendor_oversight",
        type="yes_no",
        label="Is there a written process for selecting and overseeing service providers that handle customer data?",
    ),
]
