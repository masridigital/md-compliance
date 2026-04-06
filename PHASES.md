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
| B2 | Migrate scheduler to Celery/Redis | Pending |
| B3 | CI/CD pipeline (.github/workflows) | **DONE** 2026-04-06 |
| B4 | PCI DSS v3.1 → v4.0 upgrade | **DONE** 2026-04-06 |

## Phase C: Product Roadmap

| Item | Description | Status |
|------|-------------|--------|
| C1 | Automated evidence collection | Pending |
| C2 | Continuous monitoring | Pending |
| C3 | Employee training module | Pending |
| C4 | Missing compliance frameworks (GDPR, CCPA, ABA, HITRUST) | Pending |
| C5 | Cross-framework control mapping | Pending |
| C6 | Trust portal (client-facing) | Pending |

## Integration Status

| Integration | Client | Routes | LLM Phase | UI Card | Status |
|-------------|--------|--------|-----------|---------|--------|
| Telivy | TelivyIntegration | telivy_routes.py | Phase 1 | Yes | **Active** |
| Microsoft Entra | EntraIntegration | entra_routes.py | Phase 2 | Yes | **Active** |
| NinjaOne RMM | NinjaOneIntegration | ninjaone_routes.py | - | Yes | **Active** (needs LLM phase) |
| DefensX | DefensXIntegration | defensx_routes.py | - | Yes | **Active** (needs LLM phase) |
| Blackpoint Cyber | - | - | - | Tile only | Coming Soon |
| Keeper Security | - | - | - | Tile only | Coming Soon |
| SentinelOne | - | - | - | Tile only | Coming Soon |
