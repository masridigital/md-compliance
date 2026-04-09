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
- D5: Project Detail — **PARTIAL** (header, tab pills, stat cards done; inner drawers/editors still old style)
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

### This Session (2026-04-09)
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

### Remaining Work (Priority Order)
1. **Phase D UI**: D5 inner components (drawer panels, control editor, evidence tab) — deep restyle
2. Additional integration connections (ConnectWise, Duo, KnowBe4, Veeam)
3. Training management UI page and employee completion dashboard
4. Continuous monitoring UI: drift alerts dashboard widget
5. Trust portal: NDA gate implementation, custom domain CNAME support
6. UI polish: Related Controls panel on control detail view (C5 data is ready)
