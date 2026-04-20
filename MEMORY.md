# MD Compliance — Session Memory

Last updated: 2026-04-19

## Current Phase: E (Scalability Refactoring) — E1-E5 DONE

Phase D is complete. Phase E (backend scalability) is now wrapped: E1
(split `models.py`), E2 (5 domain services), E3 (split
`SettingsService`), E4 (drop threading.Timer), E5 (`lazy="select"` on
hot paths). What remains is opportunistic follow-up migration + the
deferred UI/correctness items in the Known Issues table.

### Completed (All Sessions)

**Phase A (Architecture Hardening) — ALL 7 STEPS COMPLETE:**
- Step 1: Decoupled integrations with `run_mode` (telivy_only | microsoft_only | ninjaone_only | defensx_only | full)
- Step 2: Job stage tracking (`_update_job_status()`), 15 min poll timeout, chunk progress in UI
- Step 3: `prompt_adapters.py` — 7 model-family adapters (Claude, DeepSeek, Llama, Kimi, Gemma, Qwen, Default)
- Step 4: Adapters wired into `LLMService.chat()` + chunk size in `_run_chunked_llm`
- Step 5: Update manager Docker safety
- Step 6: Redis-backed log viewer (LPUSH/LTRIM, in-memory fallback, worker ID)
- Step 7: Storage provider hardening

**Phase B (Technical Debt) — ALL 4 ITEMS COMPLETE:**
- B1: PDF report generation (WeasyPrint pipeline) — DONE 2026-04-05
- B2: Celery/Redis scheduler (worker + beat in docker-compose, threading.Timer fallback) — DONE 2026-04-07
- B3: CI/CD pipeline — `.github/workflows/ci.yml` + `deploy.yml` — DONE 2026-04-06
- B4: PCI DSS v4.0 — 43 controls, 223 subcontrols + v3.1 deprecation support — DONE 2026-04-07

**Phase C (Product Roadmap) — ALL 6 ITEMS COMPLETE:**
- C1: Automated evidence generators (13 generators: 6 Microsoft, 3 Telivy, 3 NinjaOne, 2 DefensX) — DONE 2026-04-07
- C2: Continuous monitoring (baseline + drift detection engine) — DONE 2026-04-07
- C3: Employee training module (models, CRUD, assignments, templates) — DONE 2026-04-07
- C4: GDPR, CCPA/CPRA, ABA Model Rules, HITRUST CSF frameworks — DONE 2026-04-07
- C5: Cross-framework control mapping (50+ NIST 800-53 controls) — DONE 2026-04-07
- C6: Trust portal (public compliance status page) — DONE 2026-04-07

**Phase D (UI/UX Redesign) — COMPLETE:**
- D1: Sidebar + Top Bar — **DONE** (80px/224px, tooltips, emerald accent, DM Sans, collapse on mouse leave)
- D2: Home Dashboard — **DONE** (two-column, clean greeting, 3 feature cards, risk table, stat row)
- D3: Clients/Workspace — **DONE** (grid cards + drawer, consistent header, emerald hover/status dots)
- D4: Projects List — **DONE** (progress rings, framework badges, stat pills, card grid)
- D5: Project Detail — **DONE** (full restyle: drawer, tabs, evidence, risk register, settings, summary, checklist)
- D6: Integrations/Settings — **DONE** (4-column grid, status dots, drawer, consistent header)
- D7: Users + Activity Logs — **DONE** (AG Grid dark theme, emerald styling, meta-labels)
- D8A: Login — **DONE** (full redesign, animations, emerald gradient, OAuth buttons)
- D8B: Setup — **DONE** (hero + form, animations, emerald focus)
- D8C: Register — **DONE** (hero + animated form, emerald accents)
- D8D: Reset Password — **DONE** (centered card, emerald gradient background)

**Integration Pipeline — ALL 4 INTEGRATIONS FULLY WIRED:**
- Telivy: Phase 1 LLM analysis + 3 evidence generators
- Microsoft Entra: Phase 2 LLM analysis + 6 evidence generators
- NinjaOne: Phase 3 LLM analysis + 3 evidence generators
- DefensX: Phase 4 LLM analysis + 2 evidence generators
- Phase 5: Cross-source analysis with dynamic source listing
- `_compress_for_llm`: All 4 integrations
- Daily scheduler refresh includes all 4 integrations
- UI cards on `view_project.html` integrations tab

**Security Hardening:**
- Round 1: CSRF protection (Flask-WTF + auto-inject in fetch), error message sanitization, bare except fixes
- Round 2: Setup race condition (advisory lock), tenant isolation (notifications, WISP), stored XSS fix, open redirect fix, Telivy admin check
- Round 3 (2026-04-09): Added missing `Authorizer.get_tenant_id()` static method (was causing runtime errors on 17+ routes)
- Round 4 (2026-04-11): Open redirect fix in `is_logged_in` decorator, XSS fix in policy center TOC `generateHTML()`

**Bug Fixes Applied (2026-04-07 to 2026-04-09):**
- CRITICAL: Fix 'Unsupported LLM provider: together_ai' — added alias in `_PROVIDERS`
- CRITICAL: Fix LLM not running — was reading from empty SettingsLLM
- Fix LLM tier routing: fall back to provider default model when empty
- Fix tier config clearing: save directly to ConfigStore, skip SettingsLLM
- Fix fabricated risk data: add anti-fabrication rules to LLM prompts
- Fix risk tab navigation + deep-linking
- Fix assessment mappings: include full executive summary text in LLM data
- Map positive findings as compliance evidence + clear stale errors
- Add comprehensive LLM debug logging for all call sites
- Fix Telivy horizontal scroll in drawer
- Fix clients page N+1 project count API calls (single query now)
- Fix login hero text: responsive size + constrained to left half
- Health check: lightweight config check + yellow checking state
- Validate API key BEFORE saving — don't break existing config
- Fix sidebar collapse on mouse leave
- Performance: optimize for 8GB RAM server (1 worker + 4 threads, PG memory limits, Redis 192MB)
- RiskRegister `summary` + `evidence_data` fields + migration 0008

**Other:**
- First-run web UI setup (admin creation moved from setup.sh)
- Celery scheduler app (`celery_app.py`) created
- Framework deprecation migration (0006)
- `tests/test_prompt_adapters.py` (21 tests)
- Full Apple-inspired dark theme with emerald accent (theme.css, DM Sans font)
- CSP updated: added cdnjs.cloudflare.com to allowlist

### Session 2026-04-09
- Recovered 50 orphaned commits from detached HEAD into main
- Fixed critical security bug: `Authorizer.get_tenant_id()` was undefined but called in 17+ routes
- Fixed trust portal: added `@login_required` to config endpoints
- Fixed latent XSS: changed `x-html` to `x-text` for invite alert
- Fixed users page bug: `selectedItem.id` to `this.selectedItem.id`
- D4: Complete Projects List redesign (progress rings, framework badges, card grid)
- D5: Project Detail header, tab pills, stat cards redesigned
- D7: Users page + Activity Logs with AG Grid dark theme
- D8C: Register page redesign (hero + animated form)
- D8D: Reset Password redesign (centered card + emerald gradient)
- D3: Workspace polish (consistent header, card hover effects)
- D6: Integrations polish (consistent header, 14px radius)
- Audited full codebase against documentation — updated all docs

### This Session (2026-04-10)
- Audited CLAUDE.md against codebase — fixed D3 (PARTIAL→DONE), D5 (NOT STARTED→PARTIAL), D6 (PARTIAL→DONE) status
- **D5 Project Detail — Complete restyle of all inner components:**
  - Control drawer: new `d5-drawer` class, emerald pill tabs, info-label meta typography, cleaner action menus
  - Subcontrol drawer: matching redesign with d5-card info grid, back button, progress bars
  - Details tab: completion ring + 6-card info grid + guidance card (replaces old radial progress + grid)
  - Subcontrols tab: d5-table with d5-badge status pills, progress bars, avatars
  - Auditor Review tab: d5-card filter sidebar, d5-table feedback list, clean empty states
  - Comments tab: centered empty state with icon
  - Evidence tab: d5-overview-card with search, d5-table with file/controls badges
  - Risk Register tab: d5-overview-card filter sidebar, d5-table with status/risk badges, emerald active filters
  - Settings tab: d5-overview-card with d5-info-label inputs, tags as inline badges
  - Summary overview: d5-info-row layout with clickable navigation, emerald badges
  - Summary checklist: d5-checklist-row + d5-checklist-num numbered items (replaces old table)
- Replaced all `bg-error opacity-80` filter active states with `bg-emerald-500/15 text-emerald-300`
- **D8E/F/G: Restyled remaining auth pages:**
  - `verify_totp.html`: emerald gradient bg, centered card, large tracking code input
  - `confirm_email.html`: icon header, inline code entry, send/resend buttons
  - `set_password.html`: centered card with emerald icon, validation feedback
- Security review: CSRF tokens verified on all forms, no x-html in auth, formatComment sanitizes properly
- Updated CLAUDE.md completed steps table with D3, D5 partial, D6
- **D5 second pass — remaining tabs restyled:**
  - Policies tab: d5-table with Draft/Published badges
  - Comments tab: emerald header, clean empty state
  - Users tab: d5-table with role badges, compact edit/delete
  - Report tab: d5-overview-card sidebar selector with emerald active states
  - Audit Review tab: d5-card status cards with metrics (InfoSec/Auditor/Complete)
  - Controls tab: analytics dashboard (d5-card charts), bulk actions, AI bar
- Phase D is now effectively COMPLETE — all 11 major components restyled
- **Training management UI page (C3 UI):**
  - New `/training` route + sidebar nav link
  - Grid card layout with progress rings, stat row, create modal
  - Detail drawer with assignment table, inline assign form, completion tracking
  - Uses consistent Apple-inspired design tokens

- **Drift alerts banner on home dashboard (C2 UI):**
  - Loads from /api/v1/settings/monitoring/drift
  - Collapsible amber banner with severity icons, detection dates
  - Hidden when no drift detected
- **Related Controls panel (C5 UI):**
  - Added `mapping` to ControlMixin parent_fields (flows to frontend)
  - Cross-framework badge display in control drawer Details tab
  - Shows equivalent controls from NIST, SOC 2, ISO, PCI, HIPAA, CMMC, CSF
- **ALL auth pages now restyled (10/10):**
  - login, register, setup, reset_password (already done)
  - verify_totp, confirm_email, set_password (done this session)
  - reset_password_request, magic-login, accept, get_started (done this session)

- **Trust portal NDA gate (C6 enhancement):**
  - Alpine.js overlay when `nda_required=true` in config
  - Email + NDA checkbox acceptance form
  - Server-side logging at `/trust/<slug>/nda-accept` (rate-limited, capped at 1000 entries)
  - Client-side localStorage persistence
  - Apple-inspired styling matching trust portal design

- **Security fix:** Training update endpoint now validates content_url (http/https) and sanitizes framework_requirements (same as create)

### Session 2026-04-11
- **Doc audit**: Verified all models, methods, integrations against CLAUDE.md
- **CLAUDE.md fixes**: Added 4 missing blueprints (notification, training, trust, wisp), added Training/TrainingAssignment models to Key Models section
- **Security review (Round 4)**:
  - Ran comprehensive security audit covering XSS, CSRF, SQL injection, open redirect, secrets, auth/authz
  - **H1 FIXED**: Open redirect in `is_logged_in` decorator — added `_safe_next()` validation to `app/utils/decorators.py`
  - **H2 FIXED**: XSS in policy center TOC — added `escapeHtml()` sanitization to `generateHTML()` in `policy_center.html`
  - **H3 FIXED**: SSRF in storage test endpoints — added domain validation (Egnyte), private IP blocking (S3), UUID format check (SharePoint tenant_id)
  - **M5 FIXED**: MFA TOTP URI self-XSS — added HTML escaping before innerHTML in `profile.html`
  - Verified: CSRF globally enabled, all raw SQL parameterized, Jinja2 auto-escaping on, all routes auth-protected
- Updated PHASES.md security hardening table

### Session 2026-04-19 (Phase E + Telivy debug hardening)

Commits on `claude/continue-session-plan-4jkFL` (merged to `main`):

- **Phase E2 — Service layer rollout (5/5):**
  - `project_service.py` — 7 operations (list, get_serializable, update_basic, update_settings, delete, create_for_tenant, set_notes). 7 view endpoints migrated.
  - `risk_service.py` — 8 operations. 9 view endpoints migrated across `views.py` + `vendors.py`. Replaced raw-SQL risk queries with relationship reads.
  - `evidence_service.py` — 11 operations (list/create/update/delete at project + subcontrol level, groupings, associate, add/remove bindings). 12 view endpoints migrated. Fixed latent `Project.evidence_groupings` bug that called nonexistent `self.subcontrols()`.
  - `compliance_service.py` — 16 operations (framework seeding, policy CRUD, versions, project↔control bridge, review-status + applicability + notes, subcontrol updates). 20 view endpoints migrated.
  - `vendor_service.py` — 13 operations (vendor + app + assessment CRUD, tenant rollups, notes, categories, business units). 14 view endpoints in `vendors.py` migrated.
- **Phase E4 — threading.Timer removed:** `scheduler.py` 611 → ~460 lines. Celery + Redis now hard-required (`from celery import Celery` at module top fails fast if missing). `docker-compose.yml` celery-worker/celery-beat gate dropped — they start with `docker-compose up`. `_started` flag + `threading.Lock` replace `_timers`/`_running`. Closes the 3 scheduler Known Issues entries.
- **Phase E5 — lazy="select" on hot paths:** `ProjectControl.subcontrols`, `.tags`, `.feedback`, and `ProjectSubControl.evidence` switched off AppenderQuery. Call-sites in `api_v1/views.py`, `masri/llm_routes.py`, `masri/evidence_generators.py`, `utils/mixin_models.py`, and `models/project.py` rewritten to use list idioms.
- **Phase E3 — SettingsService god class split (7 domain services):**
  - `app/services/platform_service.py` — PlatformSettings singleton + MCP key validation
  - `app/services/branding_service.py` — TenantBranding overlaid on platform defaults
  - `app/services/llm_config_service.py` — primary SettingsLLM row
  - `app/services/storage_config_service.py` — SettingsStorage rows + default election
  - `app/services/sso_service.py` — SettingsSSO (platform + per-tenant)
  - `app/services/notification_service.py` — channels + DueDate reminders
  - `app/services/entra_config_service.py` — platform Entra credentials
  - `settings_service.py` shrank 568 → 160 lines; only Fernet primitives (`encrypt_value`/`decrypt_value`/`is_encrypted`/`EncryptedText`) remain because ~30 call-sites consume them as module-level helpers
  - 15 call-sites migrated: `settings_routes.py` (14), `context_processors.py`, `entra_routes.py`, `telivy_routes.py`, `llm_service.py`, `model_recommender.py`, `storage_router.py`, tests. Dead `SettingsService` import removed from `notification_engine.py`.
- **Telivy debug-data hardening (5 fixes):**
  - Response is a single JSON object — docstring makes the machine-only contract explicit
  - New `normalized_status` field collapses `scan_status` + `llm_status` with authoritative precedence rules:
    - `telivy.scan.scanStatus` wins over `telivy.assessment.scanStatus`
    - `llm_result.success == True` wins over stale `llm_status.status == "processing"`
  - `_mask_secret` helper redacts `telivyKey` (both `scan` and `assessment` blobs) and top-level `tenant_id`, defensively (doesn't mutate source)
  - Findings indexed by slug in both the debug response (`telivy_findings_by_slug`) and the LLM compression pass in `llm_routes.py` — slugs are stable machine ids; names drift between scans.

### Next Session — Priority Order

**Carried over from the Phase D/E tables in CLAUDE.md:**

1. **Phase D UI follow-ups** (captured in CLAUDE.md "Known UI/UX Follow-ups"):
   - Home page: hero treatment for top-level risk count + drift-alert callout refinement
   - Workspace drawer interior (SSO fields, project list) still uses legacy styling — apply `d5-drawer` internals
   - Projects page: Fraunces-serif progress ring number + `d5-framework-chip` for wrapping framework codes
   - `view_project.html` sub-tabs pending: Controls list status pills, Evidence card grid, Risk Register, Policies, Settings, Integrations, Users, Audit Review, Report — plus control drawer header + sub-tabs
   - 30-day completion chart: clamp y-axis to `[0, max(series)+10]` or switch to sparkline card for flat data

2. **Known Issues (deferred bugs in CLAUDE.md Security Audit table):**
   - `ControlMixin.generate_stats` reports "not started" on a 99% project — needs live API response from `/api/v1/projects/<pid>/controls` to diagnose (possible causes: URL-preserved filter, stale pre-loaded subs, or mismatch between `_fast_summary` SQL aggregation and `generate_stats` Python loop)
   - `has_evidence(id=...)` uses `int(id)` on shortuuid string — ValueError crash path
   - `TestingConfig` inherits `SQLALCHEMY_ENGINE_OPTIONS = {"pool_size": 5, ...}` — SQLite rejects pool_size, test suite can't run locally. Override to `{}` in TestingConfig.
   - `SMTP TLS` setting stored as string (always truthy) — can never disable via settings
   - `email_confirm_code` has no expiry — valid forever once generated
   - Drift detection baselines never auto-created — drift checks silently disabled until manual baseline
   - MFA false positives: new users flagged as "MFA disabled" (baseline check should exclude users not in baseline)
   - Missing `ondelete` on FKs, mutable `default={}` on several model columns, `PlatformSettings`/`SettingsLLM` singleton not DB-enforced

3. **Opportunistic E2 follow-ups** (as touched during feature work):
   - `project_service`: migrate control member management, tag management, project history, auditor-feedback endpoints
   - `compliance_service`: evidence-subcontrol bindings at the subcontrol level

4. **Product backlog (Phase C6+):**
   - Trust portal: custom domain CNAME support
   - Additional integrations: ConnectWise Manage/Automate, Duo Security, KnowBe4, Veeam/Datto — each follows the "Integration Methodology" section in CLAUDE.md

5. **Follow-ups from today's work to verify on next boot:**
   - Test the `/api/v1/settings/debug-data/<tid>` endpoint in the live admin UI — confirm the new `normalized_status` renders and `telivyKey` masking works on a real assessment
   - Confirm Celery workers pick up the 6 scheduled tasks on a real deploy (E4 verified on import, not on a live broker)
   - Watch `app/services/__init__.py` — if any new service is added, also update the docstring list there

### Session 2026-04-19 — afternoon (methodology + login redesign)

Work after the E2/E3/E4/E5 morning push:

- **Evidence stub bug fixed (`app/utils/mixin_models.py`):** `has_evidence()` was returning True for LLM-authored stubs (groups `auto_evidence` + `integration_scan` with no file). That inflated `progress_evidence` to 100 %, granted the +30 evidence bonus in `get_completion_progress()`, and let `is_complete()` return True on subcontrols no one had actually supported — rolling up to a project reading 99 % complete with zero uploads. Tightened `has_evidence()` to count a row only when a file is attached OR the group is outside the auto-generated set. Fixed the adjacent `int("c3xssptq")` ValueError on the `id=...` lookup branch. See `_AUTO_EVIDENCE_GROUPS` module constant.
- **METHODOLOGY.md drafted (now marked Implemented on remote):** strict compliance pipeline — 5 non-negotiable rules, 6-stage pipeline (Collect → Distill → Map → Propose → Review → Score), binary-per-subcontrol scoring, data-model diff (`kind`/`status` on `ProjectEvidence`, requirement slots on `Control`, `ai_suggestion` + `IntegrationFact` tables), client journey, F1-F6 rollout, 5 open product questions at the bottom. A parallel session / agent implemented F1-F6 + a Phase G perf pass while this session was drafting — the doc on `main` now reads "Implemented 2026-04-19".
- **Summary tile polish (`view_project.html`):** hero tile now matches rail-tile rhythm — same 12 px radius, same 1rem/1.1rem padding, same `flex-column + justify-content: space-between + min-height: 100%`. Added `.d5-hero-label` ("Completion") so all four tiles carry an uppercase peer label. Dropped Fraunces from `opsz 144` → `opsz 72` (the display-only axis was producing a wonky italic-looking "3" glyph at 2.75 rem).
- **SSO-primary login (`app/templates/auth/login.html`):** `/login` now shows Microsoft + Google buttons only. `?sso=false` reveals the local email/password form with a "Back to SSO" return path. Microsoft button is **unconditional** on the SSO view — customer wants it visible even before Entra is configured. The backend guard at `app/auth/microsoft.py:17` still flashes "Provider not configured" and bounces home if someone clicks it unconfigured, so the button stays visible-but-inert rather than disappearing. A parallel-session commit (`a76f81e`) had wrapped the button in `{% if config.ENABLE_MICROSOFT_AUTH %}` — that was overridden during the rebase because it contradicts the user-stated requirement.
- **Rebase collision:** while drafting, `origin/main` moved forward by ~12 commits (Phase F4/F5/F6 + Phase G perf + docs sync + view_project HTML-comment fixes). Rebase hit one conflict in `login.html`; resolved in favour of the SSO-primary rewrite above.

### Next Session — updated priority order

1. **Verify F1-F6 methodology implementation landed from the parallel session matches what METHODOLOGY.md describes** — spot-check migrations (`kind`/`status` on `ProjectEvidence`, `IntegrationFact` + `ai_suggestion` tables), check that `has_evidence`/`get_completion_progress`/`is_complete` use the strict binary logic from §4 Stage 6, confirm the review queue page exists and routes work end-to-end.
2. **Drawer unification (still pending user confirmation):** the control drawer's Details / Subcontrols / Review / Comments tabs don't work — user wants them all collapsed into one scrolling panel. Waiting on answers to two questions: (a) section order top-to-bottom, (b) keep tab row as jump-to anchors or drop it entirely.
3. **Flash of broken login page on successful local auth:** user reported "when I login this happens and refresh the page I'm in" — sounds like the post-login redirect goes somewhere that briefly errors before settling. Only repro path is visual; need a screenshot or HAR to diagnose. Low impact now that SSO is primary.
4. **Confirm evidence honesty reset didn't strand customers** — the `has_evidence()` tightening dropped completion % on every project with auto-stubs. METHODOLOGY.md F2 calls for a banner and a "re-open review queue" button; need to confirm the parallel session's F6 UI work shipped those.
5. Remaining bug-fix backlog from CLAUDE.md Known Issues table (SMTP TLS stored as string, `email_confirm_code` no expiry, missing `ondelete` FKs, mutable `default={}` model columns, drift baselines never auto-created, MFA baseline false positives).
