# MD Compliance — Methodology

**Status:** Proposal — 2026-04-19. Not yet implemented. Author: platform team. This
document replaces the implicit "auto-process writes whatever the LLM
returns" flow with a strict, framework-faithful pipeline. Any deviation
from what is written here is a bug.

> **First principle.** A control is compliant only when the control's
> framework-defined requirements are each met with real, verifiable
> evidence that a human has reviewed. The system never marks something
> compliant on behalf of the customer — it only tells them what's
> covered, what's missing, and what it believes would satisfy each
> requirement.

---

## 1. Why this exists

Today the auto-process pipeline conflates three very different
artefacts:

- Real evidence — a policy PDF, a SOC 2 attestation, a signed screenshot
  of Conditional Access enforcing MFA.
- Integration readings — "Entra reports 97% of users enrolled in MFA".
- LLM prose — "Based on the Entra data, MFA is in place."

All three end up as `ProjectEvidence` rows, associated to subcontrols.
Status logic (`has_evidence`, `get_completion_progress`, `is_complete`)
has been treating them as equivalent, so a project can read 99% complete
with zero uploaded artefacts. That is dishonest to the customer and
useless to an auditor.

The methodology below changes *what* the system stores, *how* things
advance through the compliance pipeline, and *what the numbers on every
dashboard mean*. Scoring and evidence reads are tightened so the only
way a control reports "complete" is for all its requirements to be met
by real evidence that a human has approved.

---

## 2. The five rules (non-negotiable)

1. **Evidence has provenance.** Every `ProjectEvidence` row carries a
   `kind` (`uploaded` | `integration_artifact` | `llm_hint`) and a
   `status` (`draft` | `proposed` | `accepted` | `rejected`). Only
   rows with `status = accepted` count toward compliance.
2. **Framework dictates requirements.** Each `Control` carries a
   machine-readable `evidence_requirements` schema describing exactly
   what must be produced (policy document, implementation proof,
   periodic-review record, etc.) and how many of each. A control is
   compliant when every required slot is filled, not when an average
   crosses a threshold.
3. **AI proposes, humans verify.** The auto-process pipeline never
   writes `review_status`, `implemented`, or `verified_at`. It produces
   proposals; a human confirms.
4. **Completion is binary per subcontrol.** A subcontrol is either
   verified or it isn't. There is no partial-credit blend between
   implementation % and evidence %.
5. **Integration findings degrade gracefully.** When a refreshed
   integration pull contradicts a previously accepted piece of
   integration evidence (drift), the evidence moves back to
   `status = proposed` and the subcontrol loses its verified state
   until re-reviewed.

---

## 3. Data model

The surface area we need is small. Additive migrations only — nothing
dropped so legacy data survives the cutover.

### 3.1 `ProjectEvidence` additions

```python
kind = db.Column(db.String, nullable=False, default="uploaded")
# one of: uploaded | integration_artifact | llm_hint
status = db.Column(db.String, nullable=False, default="draft")
# one of: draft | proposed | accepted | rejected
source = db.Column(db.String, nullable=True)
# free-form attribution — "entra:mfa_report", "telivy:scan:abc", "user:alice@org"
integration_fingerprint = db.Column(db.String, nullable=True)
# stable hash of the underlying fact (e.g. sha1 of sorted MFA user list)
# lets drift detection notice "Entra says the same thing" vs "Entra changed"
reviewed_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
reviewed_at = db.Column(db.DateTime, nullable=True)
rejection_reason = db.Column(db.Text, nullable=True)
```

Backfill: the two existing auto groups (`auto_evidence`,
`integration_scan`) map to `kind = llm_hint`, `status = proposed`. Every
other row becomes `kind = uploaded`, `status = accepted` — customers
already treated those as real.

### 3.2 `EvidenceAssociation` additions

```python
requirement_slot = db.Column(db.String, nullable=True)
# which requirement slot on the control this evidence satisfies
# (e.g. "policy_document", "implementation_proof", "periodic_review")
# NULL means "general evidence not bound to a specific requirement"
```

### 3.3 `Control.evidence_requirements`

A JSON schema on the framework control that the project mirrors onto
`ProjectControl` at creation time. Shape:

```json
{
  "slots": [
    {
      "key": "policy_document",
      "label": "Written policy covering this control",
      "min_count": 1,
      "accepted_kinds": ["uploaded"],
      "expires_after_days": 365
    },
    {
      "key": "implementation_proof",
      "label": "Configuration screenshot, export, or integration reading",
      "min_count": 1,
      "accepted_kinds": ["uploaded", "integration_artifact"],
      "expires_after_days": 180
    },
    {
      "key": "periodic_review",
      "label": "Most recent annual review sign-off",
      "min_count": 1,
      "accepted_kinds": ["uploaded"],
      "expires_after_days": 365
    }
  ]
}
```

Framework-level defaults live in `app/files/base_controls/<fw>.json`. A
project can override per-control but not drop the slots below the
framework minimum.

### 3.4 `ProjectSubControl` additions

```python
verified_at = db.Column(db.DateTime, nullable=True)
verified_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
verification_note = db.Column(db.Text, nullable=True)
```

`implemented` keeps its 0-100 range, but ONLY a human can set it to 100.
The auto-process pipeline writes a parallel `ai_suggested_implemented`
(0-100) that the UI surfaces as "AI thinks this is ~75% there based on
integration X" — it never overwrites the human value.

### 3.5 `ai_suggestion` table (new)

All AI output lives in one place so the view doesn't reach into LLM
blobs via ConfigStore keys:

```
id, project_id, subject_type ("subcontrol"|"control"|"risk"),
subject_id, kind ("evidence_mapping"|"implementation_estimate"|"risk"|"gap"),
payload JSON, confidence float, created_at, dismissed_at, accepted_at,
reviewed_by_id
```

---

## 4. Pipeline (six stages)

Replaces the current `_bg_auto_process` flow. Each stage is idempotent
and writes its own observable state so the UI can show "Collecting
Entra 3/5" in real time and the pipeline can resume after a crash.

### Stage 1 — Collect (unchanged)

For each enabled integration, pull raw data into
`ConfigStore("tenant_integration_data_{tenant_id}")` under the
integration's key. No changes to existing behaviour.

### Stage 2 — Distill (new)

Raw integration blobs are reduced to a flat list of **facts**. A fact
is a tuple `(source, subject, assertion, fingerprint, collected_at)`:

```
("entra", "user:alice@org", "mfa_enrolled=true", "sha1:...", "2026-04-19")
("ninjaone", "device:laptop-37", "bitlocker_enabled=false", "sha1:...", "2026-04-19")
("telivy", "domain:acme.com", "spf_record=missing", "sha1:...", "2026-04-19")
```

Facts are structured, machine-verifiable, and don't require an LLM to
produce. They live in a `IntegrationFact` table partitioned by tenant
and refreshed on every pull. The old `_compress_for_llm` prose is
dropped from the evidence path — it stays only as LLM context material.

### Stage 3 — Map

Each framework declares, for each control, a set of `FactPattern` rules
that would satisfy specific requirement slots. Example for "MFA
required for all users":

```yaml
control: "soc2/cc6.1"
requirement_slot: "implementation_proof"
rule:
  fact_type: "mfa_enrolled"
  source: ["entra"]
  threshold: ">= 95% of users"
  evidence_kind: "integration_artifact"
  confidence: 0.9
```

The mapper runs these rules against the current `IntegrationFact` rows
and emits `ProjectEvidence` records with `kind = integration_artifact`
and `status = proposed`, linked to the right subcontrol + slot. No LLM
involved — deterministic, reproducible, auditable.

Rules live in `app/files/fact_patterns/<framework>.yaml` and are
versioned with the framework.

### Stage 4 — Propose (LLM, narrow scope)

For controls that no rule matched and that humans haven't yet supplied
evidence for, the LLM gets a tight, control-specific prompt:

- "Here is the control text and its requirement slots."
- "Here are the integration facts the mapper found for this tenant."
- "For each unfilled requirement slot, propose either (a) an integration
  fact that would satisfy it, (b) the specific artefact the human must
  upload, or (c)'not applicable because X'."

Output goes into `ai_suggestion` with `kind = evidence_mapping` or
`gap`. Never into `ProjectEvidence` directly. The UI shows proposals as
a queue, not as filled slots.

### Stage 5 — Human review

InfoSec works a review queue. For each proposal they either:

1. **Accept** — row flips from `status = proposed` to `status = accepted`
   and counts toward compliance. `reviewed_by_id` + `reviewed_at`
   stamped.
2. **Reject with reason** — stays as `proposed` with `rejection_reason`,
   drops out of the evidence count.
3. **Upload better evidence** — creates a new `uploaded` row and
   associates it to the same slot.
4. **Mark not applicable** — subcontrol gets `is_applicable = False`
   with a justification recorded on `verification_note`.

Setting `implemented = 100` and `verified_at` is an explicit human act
on the subcontrol drawer. The UI enforces the checklist: all
requirement slots filled with `accepted` evidence, then the Verify
button unlocks.

### Stage 6 — Score (strict)

Replacing `ControlMixin.generate_stats` and
`ProjectSubControl.get_completion_progress`:

```
def subcontrol_state(sc):
    if not sc.is_applicable:
        return "not_applicable"
    slots = sc.control.evidence_requirements["slots"]
    missing = [s for s in slots if not sc.has_accepted_evidence(slot=s["key"])]
    if missing:
        if sc.implemented and sc.implemented > 0:
            return "in_progress"
        return "not_started"
    if sc.implemented != 100:
        return "ready_for_review"  # evidence in, implementation claim pending
    if sc.verified_at is None:
        return "awaiting_verification"
    if sc.project.has_auditor and sc.review_status != "complete":
        return "awaiting_auditor"
    return "complete"

def control_completion(control):
    applicable = [sc for sc in control.subcontrols if sc.is_applicable]
    if not applicable:
        return 0, "not_applicable"
    complete = sum(1 for sc in applicable if subcontrol_state(sc) == "complete")
    pct = round(complete / len(applicable) * 100)
    return pct, "complete" if pct == 100 else "in_progress" if complete else "not_started"

def project_completion(project):
    # Count COMPLETED subcontrols across the project, never average the
    # per-control completion percentages. Averaging hides the fact that
    # 100 subcontrols at 99 % complete is still zero actually-compliant
    # controls.
    total = 0
    complete = 0
    for ctrl in project.controls:
        for sc in ctrl.subcontrols:
            if not sc.is_applicable:
                continue
            total += 1
            if subcontrol_state(sc) == "complete":
                complete += 1
    return round(complete / total * 100) if total else 0
```

Evidence % is a separate, honest metric: (subcontrols with at least one
accepted piece of evidence per required slot) / (applicable
subcontrols). No averages, no implementation × 0.3 blends.

---

## 5. Client journey

A new client should reach a trustworthy picture in under an hour of
hands-on time. Here's the shape.

### Hour 0 — Onboard

1. Sign up, create a tenant, pick the framework(s) (SOC 2, HIPAA, NIST,
   ...).
2. The framework seeds `ProjectControl` + `ProjectSubControl` rows with
   requirement slots attached to each.
3. Invite the InfoSec team; assign roles.

### Hour 1 — Connect

1. Connect one or more integrations (Entra, NinjaOne, Telivy, DefensX).
   Each connection pulls raw data and runs Stage 1 + Stage 2 in the
   background. Dashboard shows: "We collected 1,247 facts across 4
   sources."
2. Stage 3 maps those facts to controls. The home dashboard now shows:
   - **Covered by integrations (proposed):** N subcontrols
   - **Gaps — need your evidence:** M subcontrols
   - **Risks detected:** K (unmet high-severity controls with explicit
     framework citation)
   - **Compliance %:** 0 (nothing is verified yet — this is the honest
     number, and the UI explains why)

### Hour 2 — Triage

1. InfoSec opens the Review Queue. For each proposed integration
   artefact: "Entra shows 97 % MFA enrolment — accept as proof of
   control SOC 2 CC6.1 'Implementation Proof' slot?"
2. Accept / reject / upload-better-evidence workflow from Stage 5. Each
   acceptance moves the compliance % honestly.

### Day 1-7 — Upload gaps

1. For the controls no integration can cover (policies, training
   records, annual reviews), the UI provides a checklist of required
   uploads per slot. The customer uploads; review queue flows.

### Steady state — Monitor

1. Daily scheduler re-pulls integration data, re-runs Stage 2. When a
   fact's fingerprint changes (e.g. a user's MFA status regresses), the
   affected `integration_artifact` evidence drops from `accepted` back
   to `proposed` and the subcontrol loses its verified state. Drift
   alert surfaced on the dashboard.
2. AI assistant suggestions appear as additive proposals, never as
   status changes. Customer decides.

### Audit day — Export

1. Report pulls only `accepted` evidence. Every row cites provenance
   (who uploaded, when it was reviewed, or which integration fact it
   maps to). No LLM-authored prose in the audit report.

---

## 6. What changes in the codebase

The existing layer maps to the new one like this:

| Today | New |
|-------|-----|
| `evidence_generators.py` writes `ProjectEvidence` rows with group `auto_evidence` | Stage 2 writes `IntegrationFact` rows. Stage 3 writes `ProjectEvidence` rows with `kind = integration_artifact`, `status = proposed`. No more hard-coded generator functions. |
| `llm_routes.py::_bg_auto_process` runs LLM phases that write `review_status` + create evidence | Stage 4 only — scoped LLM call producing `ai_suggestion` rows. Never writes status, never writes evidence directly. |
| `ProjectControl.review_status` flips from `infosec action` → `ready for auditor` automatically | Only humans flip review_status. AI can propose the next state via `ai_suggestion`. |
| `has_evidence()` returns `bool(self.evidence)` with the recent `_AUTO_EVIDENCE_GROUPS` guard | `has_evidence(slot=None)` checks for an `accepted` row of the right `kind` on that slot. |
| `get_completion_progress()` blends `impl × 0.7 + ev × 0.3` | Binary subcontrol state (see §4 Stage 6). Control completion = count of complete subs ÷ applicable. |
| `generate_stats` computes average implemented + average evidence | Recomputes per-slot coverage + status counts. Returns the counts the UI needs for honest copy. |

---

## 7. Rollout — six phases

Done in this order so customers always see an honest picture during the
transition.

### F1 — Data-model migrations (one sprint)

- Add the columns in §3.1, §3.2, §3.4.
- Create `IntegrationFact` and `ai_suggestion` tables.
- Backfill existing `ProjectEvidence` rows to `kind/status` per §3.1.
- Ship with no behaviour change — old pipeline keeps writing, new
  columns are populated but unused.

### F2 — Scoring rewrite (one sprint)

- Replace `has_evidence`, `get_completion_progress`, `is_complete`,
  and `ControlMixin.generate_stats` with the strict implementations in
  §4 Stage 6.
- Add a `legacy_completion_progress` fallback so any code that still
  calls the old method raises loudly in dev, warns in prod.
- Update every UI surface that prints percentages or status (project
  summary, control drawer, dashboards, reports). Numbers will drop,
  dramatically for some customers. We ship a banner explaining the
  reset and a one-click "re-open review queue" that flips legacy auto
  evidence to `status = proposed`.

### F3 — Fact extraction (two sprints)

- Port each current `_compress_for_llm` section (`telivy`, `entra`,
  `ninjaone`, `defensx`) into a fact extractor producing
  `IntegrationFact` rows.
- Write unit tests for every extractor: given a known raw blob, assert
  exactly these facts come out.

### F4 — Rule-based mapper (two sprints)

- Author `fact_patterns/soc2.yaml` + `hipaa.yaml` + `nist_800_53.yaml`
  first. Each rule cites its framework source ("SOC 2 CC6.1 requires
  MFA per AICPA TSP § …") in a `rationale` field for the UI.
- Stage 3 runs every mapper on each scheduler pass. Output goes into
  `ProjectEvidence` with `status = proposed`. Review queue populates.

### F5 — LLM proposal narrowing (one sprint)

- Rewrite the LLM prompts in `llm_routes.py` to only run on
  unmapped-after-Stage-3 subcontrols with a strict JSON output schema
  (per slot). All output routes into `ai_suggestion`; the existing
  `[Auto-Mapped]` prefix on `ProjectControl.notes` is removed.
- Remove `_bg_auto_process`'s ability to touch `review_status`,
  `implemented`, or `verified_at`.

### F6 — UI surface (two sprints)

- Control drawer: requirement checklist with per-slot evidence
  upload/review.
- Review queue page: list of all `proposed` evidence across the
  project, batch accept/reject, keyboard shortcuts.
- Dashboard: "what's covered / what's missing / what's risky" three-up,
  calibrated to the strict numbers.
- Audit report: strict filter — only `accepted` evidence appears;
  provenance column on every row.

Migration plan for customers already live: on the day F2 ships we email
every tenant admin with the numerics delta and link them to the review
queue. The "compliance %" number will drop; the "proposed evidence to
review" number will spike.

---

## 8. Open questions

These need product-level answers before F1:

1. **Expiry rules** — SOC 2 policies are reviewed annually; a policy
   older than 12 months should move back to `proposed` regardless of
   integration state. Confirm default expiry per framework.
2. **Auditor involvement** — does "complete" require an external auditor
   sign-off on top of InfoSec verification, or is InfoSec verification
   enough for an internal readiness dashboard? Implementation supports
   both via `review_status` — we need the default.
3. **Multi-framework overlap** — one piece of accepted evidence often
   satisfies the same slot across multiple frameworks. Cross-framework
   mapping (Phase C5) exists but is off by default. Turn on.
4. **Risk severity scoring** — integration findings map to framework
   citations, but severity (critical / high / medium / low) should come
   from framework-specific weights (e.g. PCI DSS treats
   non-encryption-at-rest as critical; SOC 2 CC6 does not). Need a
   weight table per framework.
5. **Drift grace period** — when an integration fact regresses, do we
   immediately unverify or give 7 days for the team to respond? Default
   proposed: immediate unverify + 7-day reminder before dropping the
   subcontrol from "complete" rollup.

Each of these should be decided and pinned before the code lands.
Defaults above are the author's recommendation.
