# MD Compliance — Session Memory

Last updated: 2026-04-09

## Current Phase: D (UI/UX Redesign)

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

**Phase D (UI/UX Redesign) — NEARLY COMPLETE:**
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

### Remaining Work (Priority Order)
1. Additional integration connections (ConnectWise, Duo, KnowBe4, Veeam)
2. Training management UI page and employee completion dashboard
3. Continuous monitoring UI: drift alerts dashboard widget
4. Trust portal: NDA gate implementation, custom domain CNAME support
5. UI polish: Related Controls panel on control detail view (C5 data is ready)
6. Minor D5 polish: modal dialogs, toast styles
