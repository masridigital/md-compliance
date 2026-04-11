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
