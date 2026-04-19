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

## Phase E: Scalability Refactoring — IN PROGRESS

**Goal**: Domain-driven architecture, service layer, production-grade background jobs.
**Execution order:** E1 -> E2 -> E3, E1 -> E5, E4 (independent)

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
**Status**: NOT STARTED — depends on E1

Move DB mutations out of views into `app/services/`. Views become thin wrappers: parse request -> call service -> return response.

| Service | Covers |
|---------|--------|
| `project_service.py` | project CRUD, control management, progress |
| `risk_service.py` | risk CRUD, risk scoring |
| `evidence_service.py` | evidence upload, association, generation |
| `compliance_service.py` | framework management, control mapping |
| `vendor_service.py` | vendor CRUD, assessments |

### E3: Split `SettingsService` God Object
**Status**: NOT STARTED — depends on E2

Break 20+ method `SettingsService` into: `platform_service`, `branding_service`, `llm_config_service`, `storage_config_service`, `sso_service`, `notification_service`, `entra_config_service`.

### E4: Remove `threading.Timer` Fallback
**Status**: NOT STARTED — independent

Make Redis + Celery hard requirement. Remove threading.Timer fallback. Add Celery health check to startup.

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
