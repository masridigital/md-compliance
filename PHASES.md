# MD Compliance — Phase Definitions

## Phase A: Architecture Hardening — COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 1 | Decouple Telivy from Microsoft (run_mode parameter) | **DONE** 2026-04-06 |
| 2 | Job stages + extended poll window (15 min, chunk progress) | **DONE** 2026-04-06 |
| 3 | Prompt adapter layer (7 model-family adapters) | **DONE** 2026-04-06 |
| 4 | Wire adapters into all LLM prompts (auto in LLMService.chat()) | **DONE** 2026-04-06 |
| 5 | Update manager Docker safety | **DONE** 2026-04-05 |
| 6 | Redis-backed log viewer (LPUSH/LTRIM + fallback) | **DONE** 2026-04-06 |
| 7 | Storage provider hardening | **DONE** 2026-04-05 |

## Phase B: Technical Debt — COMPLETE

| Item | Description | Status |
|------|-------------|--------|
| B1 | PDF report generation (WeasyPrint) | **DONE** 2026-04-05 |
| B2 | Migrate scheduler to Celery/Redis | **DONE** 2026-04-07 |
| B3 | CI/CD pipeline (.github/workflows) | **DONE** 2026-04-06 |
| B4 | PCI DSS v3.1 → v4.0 upgrade (43 controls, 223 subcontrols) | **DONE** 2026-04-07 |

## Phase C: Product Roadmap — COMPLETE

| Item | Description | Status |
|------|-------------|--------|
| C1 | Automated evidence collection (13 generators) | **DONE** 2026-04-07 |
| C2 | Continuous monitoring (baseline + drift detection) | **DONE** 2026-04-07 |
| C3 | Employee training module (models, CRUD, assignments, 4 templates) | **DONE** 2026-04-07 |
| C4 | Missing compliance frameworks (GDPR, CCPA, ABA, HITRUST) | **DONE** 2026-04-07 |
| C5 | Cross-framework control mapping (50+ NIST controls, bidirectional) | **DONE** 2026-04-07 |
| C6 | Trust portal (public compliance status page) | **DONE** 2026-04-07 |

## Phase D: UI/UX Redesign — IN PROGRESS

Apple-inspired design system: DM Sans font, emerald #10b981 accent, charcoal surfaces, 12px card radius.

| Step | Component | Status | Notes |
|------|-----------|--------|-------|
| D1 | Sidebar + Top Bar | **DONE** 2026-04-08 | 80px/224px, tooltips, emerald accent, collapse on hover |
| D2 | Home Dashboard | **DONE** 2026-04-08 | Two-column, feature cards, risk table, stat row |
| D3 | Clients/Workspace | **DONE** 2026-04-09 | Grid cards, drawer, consistent header, emerald hover |
| D4 | Projects List | **DONE** 2026-04-09 | Progress rings, framework badges, stat pills |
| D5 | Project Detail | **DONE** 2026-04-10 | Full restyle: drawer, tabs, evidence, risk register, settings, summary |
| D6 | Integrations/Settings | **DONE** 2026-04-09 | 4-column grid, status dots, drawer, consistent header |
| D7 | Users + Activity Logs | **DONE** 2026-04-09 | AG Grid dark theme, emerald styling, meta-labels |
| D8A | Login | **DONE** 2026-04-08 | Full redesign with animations |
| D8B | Setup | **DONE** 2026-04-08 | Hero + form with animations |
| D8C | Register | **DONE** 2026-04-09 | Hero + animated form, emerald accents |
| D8D | Reset Password | **DONE** 2026-04-09 | Centered card, emerald gradient |

## Integration Status

| Integration | Client | Routes | LLM Phase | Evidence Generators | UI Card | Status |
|-------------|--------|--------|-----------|-------------------|---------|--------|
| Telivy | TelivyIntegration | telivy_routes.py | Phase 1 | 3 | Yes | **Active** |
| Microsoft Entra | EntraIntegration | entra_routes.py | Phase 2 | 6 | Yes | **Active** |
| NinjaOne RMM | NinjaOneIntegration | ninjaone_routes.py | Phase 3 | 3 | Yes | **Active** |
| DefensX | DefensXIntegration | defensx_routes.py | Phase 4 | 2 | Yes | **Active** |
| Blackpoint Cyber | - | - | - | - | Tile only | Coming Soon |
| Keeper Security | - | - | - | - | Tile only | Coming Soon |
| SentinelOne | - | - | - | - | Tile only | Coming Soon |

## Security Hardening

| Round | What | Date |
|-------|------|------|
| 1 | CSRF (Flask-WTF + fetch auto-inject), error sanitization, bare except fixes | 2026-04-07 |
| 2 | Setup advisory lock, tenant isolation, stored XSS fix, open redirect fix | 2026-04-07 |
| 3 | Missing `Authorizer.get_tenant_id()` — 17+ routes affected | 2026-04-09 |
| 4 | Open redirect fix in `is_logged_in`, XSS fix in policy center TOC | 2026-04-11 |
| 5 | Deep audit: JWT expiry, TOTP brute-force, MCP OAuth bypass, 25+ fixes | 2026-04-12 |

## Phase E: Scalability Refactoring — COMPLETE (E1-E5)

**Goal**: Domain-driven architecture, service layer, production-grade background jobs.
**Execution order:** E1 -> E2 -> E3, E1 -> E5, E4 (independent)

| Step | Status | Landed |
|------|--------|--------|
| E1 — split `models.py` | **DONE** | 2026-04-14 |
| E2 — service layer (5/5) | **DONE** | 2026-04-19 |
| E3 — split `SettingsService` | **DONE** | 2026-04-19 |
| E4 — drop threading.Timer | **DONE** | 2026-04-19 |
| E5 — `lazy="select"` on hot paths | **DONE** | 2026-04-19 |

Opportunistic follow-ups remain (see CLAUDE.md "Pending Refactoring
Order") but no blocking Phase E work is outstanding.

### Quick Wins (completed 2026-04-14)

| Item | Description | Files |
|------|-------------|-------|
| N+1 fix | Batch-fetch subcontrols on controls endpoint | `api_v1/views.py`, `utils/mixin_models.py` |
| Context cache | Session-cache tenant branding (5 min TTL), app-cache LLM flag | `masri/context_processors.py` |
| Auth decorator | `@requires_auth()` wraps Authorizer boilerplate | `utils/decorators.py` |
| Command Palette | Cmd+K global nav with project search | `templates/layouts/sidebar-nav.html` |
| Optimistic UI | Instant review status + subcontrol updates | `templates/view_project.html` |

### E1: Split `models.py` into Domain Modules
**Status**: **DONE** 2026-04-14
**Risk**: Low (backwards-compatible re-exports)

Split the 5,161-line `app/models.py` (47 classes, 57 `lazy="dynamic"`) into domain modules. `__init__.py` re-exports everything so 106 importing files don't break.

```
app/models/
    __init__.py    # Re-exports all classes (backwards compat)
    base.py        # db, EncryptedText, shared imports
    tenant.py      # Tenant, TenantMember, TenantMemberRole, DataClass
    auth.py        # User, Role, UserRole
    framework.py   # Framework, Policy, Control, SubControl
    project.py     # Project, ProjectMember, ProjectControl, ProjectSubControl,
                   #   ProjectPolicy, ProjectEvidence, EvidenceAssociation, CompletionHistory
    risk.py        # RiskRegister, RiskComment, RiskTags
    vendor.py      # Vendor, VendorApp, VendorFile, VendorHistory, Finding
    assessment.py  # Assessment, Form, FormSection, FormItem, FormItemMessage, AssessmentGuest
    comments.py    # ControlComment, SubControlComment, ProjectComment, AuditorFeedback
    policy.py      # PolicyVersion, PolicyAssociation, ProjectPolicyAssociation, PolicyLabel, PolicyTags
    tags.py        # Tag, ControlTags, ProjectTags
    config.py      # ConfigStore, Logs
```

**Validation**: `python -c "from app.models import *"` + Docker build + health check.

**Result (2026-04-14):** 5,161-line monolith split into 11 domain modules (48 classes). `__init__.py` re-exports all classes — 106 importing files unchanged. Event listeners + `login.user_loader` live in `__init__.py`. No module exceeds ~1,150 lines. Granularity is per-domain-aggregate, not per-class — modules only warrant further splitting if they exceed ~1,000 lines or contain unrelated concerns.

| Module | Classes | Lines |
|--------|---------|-------|
| `project.py` | 8 | 1,155 |
| `assessment.py` | 6 | 922 |
| `tenant.py` | 2 | 795 |
| `vendor.py` | 6 | 560 |
| `auth.py` | 5 | 553 |
| `framework.py` | 5 | 379 |
| `policy.py` | 4 | 321 |
| `config.py` | 2 | 238 |
| `risk.py` | 3 | 203 |
| `comments.py` | 4 | 123 |
| `tags.py` | 3 | 83 |

### E2: Service Layer for Core Business Logic
**Status**: **all five services landed** 2026-04-19 — remaining project_service operations (control CRUD, member management, tags) roll in as opportunistic cleanups during normal feature work.

Moving DB mutations out of views into `app/services/`. Views become thin wrappers: parse request → call service → serialise response. Conventions documented in `app/services/__init__.py`:

1. Services accept domain objects, not IDs. Auth stays in the view.
2. Services own their `db.session.commit()` calls.
3. Services return domain objects; views own serialisation.
4. Services may `abort(...)` on domain-invariant violations.
5. No Flask request/response objects in services.

| Service | Status | Covers |
|---------|--------|--------|
| `project_service.py` | **pilot landed 2026-04-19** — 7 operations (`list_for_user`, `get_serializable`, `update_basic`, `update_settings`, `delete`, `create_for_tenant`, `set_notes`). Views updated: `get_project`, `update_project`, `delete_project`, `create_project`, `get_projects_in_tenant`, `update_settings_in_project`, `update_scratchpad_for_project`. | project CRUD, control management, progress |
| `risk_service.py` | **landed 2026-04-19** — 8 operations (`list_for_project`, `list_for_tenant`, `create_for_project`, `update_in_project`, `create_for_tenant`, `update`, `delete`, `add_comment`, `create_from_feedback`). Views updated in both `views.py` (5 endpoints) and `vendors.py` (4 endpoints). Replaced raw-SQL risk queries with relationship-based reads. | risk CRUD, risk scoring |
| `evidence_service.py` | **landed 2026-04-19** — 11 operations (list/create/update/delete at project + subcontrol level, file helpers, groupings, associate_with_controls, add/remove evidence-subcontrol bindings). 12 view endpoints migrated. Also fixed the latent `Project.evidence_groupings` bug that called the nonexistent `self.subcontrols()`. | evidence upload, association, generation |
| `compliance_service.py` | **landed 2026-04-19** — 16 operations covering framework seeding, tenant + project policy CRUD, policy versions, generic policy + control mutations, project ↔ control bridge, review-status + applicability + notes on project controls, and subcontrol updates. 20 view endpoints migrated. | framework management, control mapping |
| `vendor_service.py` | **landed 2026-04-19** — 13 operations covering vendor + app + assessment CRUD, tenant-level rollups, notes, categories, business units. 14 view endpoints in `vendors.py` migrated. | vendor CRUD, assessments |

Remaining project operations that still live in views (control CRUD, member management, tag management, project history, evidence association at subcontrol level) will migrate as the per-domain services land — keeping each commit reviewable.

### E3: Split `SettingsService` God Object
**Status**: **DONE** 2026-04-19

The `SettingsService` static-method class in `app/masri/settings_service.py`
(~400 lines, 17 methods across 9 unrelated domains) is gone. In its
place, seven per-domain service modules under `app/services/`:

| Module | Responsibilities |
|--------|------------------|
| `platform_service` | Singleton `PlatformSettings` + MCP API key validation |
| `branding_service` | `TenantBranding` overlaid on platform defaults |
| `llm_config_service` | Primary `SettingsLLM` row (provider / model / key) |
| `storage_config_service` | `SettingsStorage` provider rows + default election |
| `sso_service` | `SettingsSSO` platform-wide + per-tenant records |
| `notification_service` | `SettingsNotifications` channels + `DueDate` reminders |
| `entra_config_service` | Platform-level Entra credentials (Fernet at rest) |

`settings_service.py` keeps only the encryption primitives (`_get_fernet`,
`encrypt_value`, `decrypt_value`, `is_encrypted`, `EncryptedText`) — it
shrank from 568 to 160 lines. Those helpers stay put because ~30
callers (model column definitions, integrations, scheduler) import them
directly as module-level utilities; moving them would churn unrelated
files without benefit.

Call-sites migrated:
- `app/masri/settings_routes.py` — 14 call-sites across Platform /
  Branding / LLM / Storage / SSO / Notification / Due-date / Entra
  endpoints.
- `app/masri/context_processors.py`, `app/masri/entra_routes.py`,
  `app/masri/telivy_routes.py`, `app/masri/llm_service.py`,
  `app/masri/model_recommender.py`, `app/masri/storage_router.py` —
  re-pointed at the split modules.
- `app/masri/notification_engine.py` — dead `SettingsService` import
  removed (was imported but never called).
- `tests/test_entra_routes.py` — updated to import
  `entra_config_service` directly.

Verified end-to-end on SQLite: app boots, every new service round-trips
(create/update/read/delete), Fernet encryption survives, overdue
flagging works.

### E4: Remove `threading.Timer` Fallback
**Status**: **DONE** 2026-04-19

`scheduler.py` collapsed from 611 lines to ~460 — the `_timers` list, `_schedule_recurring`, `_wrapper` reschedule plumbing, and the "Celery not available" fallback branch all gone. What remains is task-body implementations (`_task_*`) that Celery workers call via the tasks defined in `celery_app.py`.

Hard changes:
- `celery_app.py` drops the graceful-ImportError pattern — `from celery import Celery` at module top. If `celery` is not installed, the app fails at import time with a clear error.
- `MasriScheduler.start` now binds the Flask app, calls `init_celery`, and logs a single WARNING line if the broker ping fails (instead of silently switching to timers). The web process still boots — workers may come up after web.
- `docker-compose.yml` celery-worker and celery-beat services no longer gated behind `profiles: celery`. They now start with `docker-compose up` by default.
- `MasriScheduler._timers` / `_running` replaced with a single `_started` + `threading.Lock` guarding `start()` idempotency. Eliminates the "Thread-unsafe `_running`/`_timers`" and "Missing `db.session.remove()` in threading.Timer tasks" entries from the Known Remaining Issues table.

Verified end-to-end on SQLite: app boots, scheduler registers, all 6 Celery tasks (`task_due_reminders`, `task_drift_detection`, `task_auto_update`, `task_integration_refresh`, `task_model_recommendations`, `task_backup_integration_data`) visible to the Celery app, broker-unreachable case logs cleanly.

### E5: Replace `lazy="dynamic"` on Hot Paths
**Status**: **DONE** 2026-04-19

Switched four high-traffic relationships to `lazy="select"`:
`ProjectControl.subcontrols`, `.tags`, `.feedback`, and
`ProjectSubControl.evidence`. Removed the N+1 AppenderQuery pattern on
these attributes — each parent now loads its collection once as a list.
Call-sites across `api_v1/views.py`, `masri/llm_routes.py`,
`masri/evidence_generators.py`, `utils/mixin_models.py`, and
`models/project.py` rewritten to use list idioms (`sorted`, list
comprehensions, `len`, truthiness) instead of query chaining.

## Phase F: Validation Methodology — IN PROGRESS

**Goal**: Strict compliance pipeline with verifiable facts, clear mapping, and strict scoring.

| Step | Component | Status | Notes |
|------|-----------|--------|-------|
| F1 | Data-model migrations | **DONE** 2026-04-19 | `IntegrationFact`, `AiSuggestion`, updated columns on `ProjectEvidence` |
| F2 | Scoring rewrite | **DONE** 2026-04-19 | strict stats, no partial implementation points, strict project summary |
| F3 | Fact extraction | **DONE** 2026-04-19 | evidence_generators rewritten to output `IntegrationFact` rows |
| F4 | Rule-based mapper | **DONE** 2026-04-19 | deterministic framework mapping with rule execution engine and YAML patterns |
| F5 | LLM narrowing | Pending | restrict AI to proposals vs mutations |
| F6 | UI surface | **PARTIAL** | collapsed drawer complete |
