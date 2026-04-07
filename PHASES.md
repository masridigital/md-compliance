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

## Phase B: Technical Debt

| Item | Description | Status |
|------|-------------|--------|
| B1 | PDF report generation (WeasyPrint) | **DONE** 2026-04-05 |
| B2 | Migrate scheduler to Celery/Redis | **DONE** 2026-04-07 |
| B3 | CI/CD pipeline (.github/workflows) | **DONE** 2026-04-06 |
| B4 | PCI DSS v3.1 → v4.0 upgrade (43 controls, 223 subcontrols) | **DONE** 2026-04-07 |

## Phase C: Product Roadmap

| Item | Description | Status |
|------|-------------|--------|
| C1 | Automated evidence collection (13 generators) | **DONE** 2026-04-07 |
| C2 | Continuous monitoring (baseline + drift detection) | **DONE** 2026-04-07 |
| C3 | Employee training module (models, CRUD, assignments, 4 templates) | **DONE** 2026-04-07 |
| C4 | Missing compliance frameworks (GDPR, CCPA, ABA, HITRUST) | **DONE** 2026-04-07 |
| C5 | Cross-framework control mapping (50+ NIST controls, bidirectional) | **DONE** 2026-04-07 |
| C6 | Trust portal (client-facing) | Pending |

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
