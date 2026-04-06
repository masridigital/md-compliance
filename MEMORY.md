# MD Compliance — Roadmap & Memory

> Implementation roadmap, technical debt, completed work, and pending features.
> See `CLAUDE.md` for core reference and `INTEGRATIONS.md` for integration specs.

---

## Implementation Roadmap

### Phase A: Architecture Hardening (Current Sprint)

| Step | What | Status | Files |
|------|------|--------|-------|
| ~~5~~ | ~~Update manager Docker safety~~ | **DONE** | `update_manager.py`, `scheduler.py`, `system_info.html` |
| ~~7~~ | ~~Storage provider hardening~~ | **DONE** | `storage_providers.py`, `entra_routes.py` |
| ~~1~~ | ~~Decouple Telivy from Microsoft~~ | **DONE** | `llm_routes.py`, `integrations.html`, `view_project.html` |
| ~~2~~ | ~~Add job stages + extend poll~~ | **DONE** | `llm_routes.py`, `integrations.html`, `view_project.html` |
| ~~3~~ | ~~Create prompt adapter layer~~ | **DONE** | `prompt_adapters.py`, `llm_service.py` |
| ~~4~~ | ~~Wire adapters into all prompts~~ | **DONE** | `llm_routes.py`, `llm_service.py`, `risk_profiles.py` |
| 6 | Redis-backed log viewer | Pending | `log_buffer.py`, `__init__.py` |

#### Step 1: Decouple Telivy from Microsoft
- Add `run_mode` parameter to `auto_process`: `telivy_only | microsoft_only | full`
- `_bg_auto_process` skips Microsoft when `run_mode=telivy_only` and vice versa
- Frontend: Re-run on Telivy sends `telivy_only`, Microsoft sends `microsoft_only`
- LLM phases auto-skip: Phase 1 skips if no Telivy, Phase 2 skips if no Microsoft, Phase 3 skips if only one source

#### Step 2: Job Stages + Extended Poll Window
- Add `_update_job_status(tenant_id, stage, detail)` helper writing to ConfigStore
- Stages: `collecting_telivy → collecting_microsoft → computing_risk_profiles → analyzing_phase1 → analyzing_phase2 → analyzing_cross_source → generating_evidence → syncing_progress → done`
- Frontend: extend poll from 5 min to 15 min, show stage name + chunk progress ("Analyzing Telivy 3/10")

#### Step 3: Prompt Adapter Layer
New `app/masri/prompt_adapters.py` with model-family-specific adapters:

| Adapter | Detection | Chunk | Temp | Strategy |
|---------|-----------|-------|------|----------|
| `ClaudeAdapter` | "claude" | 15 | Keep | XML tags, evidence citations, conservative conclusions |
| `DeepSeekAdapter` | "deepseek" | 8 | 0.1 max | Single objective, explicit JSON schema |
| `LlamaAdapter` | "llama" | 10 | Keep | Emphasize JSON-only, no explanation |
| `KimiAdapter` | "kimi"/"moonshot" | 12 | Keep | Broad context, rigid output |
| `GemmaAdapter` | "gemma" | 5 | 0.1 max | Extractive only, no cross-source |
| `QwenAdapter` | "qwen" | 10 | Keep | Structured examples, good JSON |
| `DefaultAdapter` | fallback | 10 | Keep | Current behavior |

Each provides: `adapt_system()`, `adapt_chunk_size()`, `adapt_temperature()`, `adapt_json_instruction()`, `adapt_max_tokens()`

#### Step 4: Wire Adapters Into All 10 Prompts
1. Phase 1: Telivy analysis (`llm_routes.py`)
2. Phase 2: Microsoft analysis (`llm_routes.py`)
3. Phase 3: Cross-source (`llm_routes.py`)
4. Assist-gaps recommendations (`llm_routes.py`)
5. Risk narratives (`risk_profiles.py`)
6. Model recommender (`model_recommender.py`)
7. Control assessment (`llm_service.py`)
8. Policy drafting (`llm_service.py`)
9. Gap narrative (`llm_routes.py`)
10. Risk scoring (`llm_routes.py`)

#### Step 6: Redis-Backed Log Viewer
- `BufferHandler.emit()` pushes to Redis LIST (LPUSH + LTRIM 500)
- `get_recent_logs()` reads from Redis (LRANGE)
- Fallback to in-memory if Redis unavailable
- Add worker ID to entries

---

### Phase B: Technical Debt (Fix Before New Features)

| Item | What | Files | Priority |
|------|------|-------|----------|
| ~~B1~~ | ~~Complete PDF report generation~~ | `app/utils/reports.py` | **DONE** |
| B2 | Migrate scheduler to Celery/Redis | `app/masri/scheduler.py`, `docker-compose.yml` | High — threading.Timer unreliable in multi-worker |
| B3 | Add CI/CD pipeline | New `.github/workflows/` | High — no automated testing or deployment |
| B4 | Upgrade PCI DSS v3.1 → v4.0 | `app/files/base_controls/pci_3.1.json` | High — v3.1 deprecated March 2024 |
| B5 | Flask version cap | `requirements.txt` | High — `Flask>=2.3.3` allows 3.x accidentally, cap at `<3.0` |
| B6 | Add test coverage | `tests/` | High — only 5 test files, no API/LLM/WISP tests |
| B7 | Add DB connection pooling | `config.py` | High — no pool_size/max_overflow configured |
| B8 | SQLite→PostgreSQL in tests | `tests/conftest.py` | Medium — SQLite won't catch PG-specific issues |

#### B2: Migrate Scheduler to Celery/Redis
- **Current state**: `app/masri/scheduler.py` — 6 tasks on `threading.Timer`
- **Problem**: Timers lost on worker restart, no persistence, no retry, can double-fire in multi-worker
- **Target**: Celery with Redis broker (Redis already in docker-compose for sessions)
- **Tasks to migrate**: due_reminders (1h), drift_detection (24h), auto_update (1h), integration_refresh (24h), model_recommendations (7d), integration_backup (24h)
- **Keep**: `MASRI_SCHEDULER_ENABLED` env toggle, graceful fallback to threading.Timer if Redis unavailable

#### B3: CI/CD Pipeline
- **Add**: `.github/workflows/ci.yml` — lint, type-check, unit tests on PR
- **Add**: `.github/workflows/deploy.yml` — build + push Docker image on merge to main
- **Tests**: Start with model tests, route smoke tests, integration client mocks
- **Linting**: flake8 or ruff, basic security scan (bandit)

#### B4: PCI DSS v3.1 → v4.0 Upgrade
- **Current**: `app/files/base_controls/pci_3.1.json` (v3.1 — deprecated March 2024)
- **Action**: Create `pci_dss_v4.0.json` with all v4.0 requirements (64 new requirements vs v3.2.1)
- **Key v4.0 additions**: Targeted risk analysis, MFA everywhere, authenticated vulnerability scanning, encrypted passwords, e-commerce skimming detection, security awareness training
- **Migration**: Existing PCI projects should offer upgrade path (map v3.1 controls → v4.0 equivalents)
- **Keep v3.1**: Legacy projects may still reference it; don't delete, mark as deprecated

---

### Phase C: Product Roadmap (by Priority)

#### C1: Automated Evidence Collection (Highest Priority)
**Problem**: Vanta has 375+ integrations, we have 3 (Telivy, Entra, Intune). Gap is the #1 competitive weakness.

**Immediate (existing data)**:
- Auto-generate evidence artifacts from Entra ID/Intune data already collected:
  - MFA enrollment report → evidence for access control controls
  - Device compliance report → evidence for endpoint protection controls
  - Conditional Access policy export → evidence for authentication controls
  - Secure Score snapshot → evidence for security posture controls
  - Sign-in anomaly report → evidence for monitoring controls
- Create `app/masri/evidence_generators.py` with per-source generators
- Each generator: query ConfigStore cache → format evidence document → create `ProjectEvidence` record
- Run as part of auto-process pipeline (new stage after LLM analysis)

**Next integrations (priority order)**:
1. **NinjaRMM** — endpoint management, patching status, AV status, remote access logs
2. **ConnectWise Manage** — ticket system, asset inventory, SLA compliance
3. **ConnectWise Automate** — patch compliance, script execution, monitoring alerts
4. **Duo Security** — MFA provider, access device health
5. **KnowBe4** — security awareness training completion (ties into C3)
6. **Veeam/Datto** — backup verification evidence

#### C2: Continuous Monitoring
**Problem**: Current drift detection is passive — checks every 24h for 90-day-stale controls. No real-time configuration change detection.

- **Webhook receivers**: Accept real-time events from Entra ID (via Azure Event Hub), NinjaRMM, ConnectWise
- **Configuration baseline**: Snapshot known-good state
- **Delta detection**: Compare current state to baseline on each data refresh
- **Alert on drift**: Policy removed, MFA disabled for user, compliance policy changed, new admin added
- **Dashboard widget**: "Configuration changes since last audit" with timeline

#### C3: Employee Training Module
**Problem**: 7 of 14 competitors include training. FTC Safeguards explicitly requires training documentation.

- **Models**: `Training` (content), `TrainingAssignment` (per-user completion tracking)
- **Blueprint**: `app/masri/training_routes.py` — CRUD + assignment + completion
- **Built-in content**: FTC Safeguards template, HIPAA security awareness, general security awareness
- **Evidence integration**: Training completion auto-generates evidence for applicable controls

#### C4: Missing Compliance Frameworks

| Framework | Why | Target Market |
|-----------|-----|---------------|
| **PCI DSS v4.0** | v3.1 deprecated, v4.0 mandatory since March 2025 | Retail, e-commerce |
| **GDPR** | EU data protection | EU-facing companies |
| **CCPA/CPRA** | California consumer privacy | CA-facing companies |
| **ABA Model Rules** | **Zero competitors** — massive white space | Law firms |
| **HITRUST CSF** | Healthcare-specific, maps to HIPAA + NIST | Healthcare, insurers |

#### C5: Cross-Framework Control Mapping
- `Control.mapping` field (`models.py:1921`, `db.Column(db.JSON(), default={})`) exists but is unused
- Populate with cross-references: `{"nist_800_53": ["AC-2"], "soc2": ["CC6.1"], ...}`
- UI: "Related Controls" panel showing equivalent controls across frameworks

#### C6: Trust Portal
- Public route: `/trust/{tenant_slug}` — unauthenticated, rate-limited
- Displays: Compliance %, last audit date, certifications, security contact
- Documents: Downloadable reports with optional NDA gate

---

### Phased Build Roadmap

**Phase 1: Foundation (Months 1-3) — Make It Sellable**
- P0: Complete PDF reports, scheduler migration, CI/CD, PCI v4.0
- P0: Add GDPR + CCPA frameworks, auto-evidence from Entra, compliance dashboard, ABA Model Rules

**Phase 2: Differentiation (Months 3-6) — Win Against ControlMap**
- P1: Cross-framework mapping engine, NinjaRMM pipeline, ConnectWise PSA
- P1: Employee training module, HITRUST, security questionnaire auto-response, active drift detection

**Phase 3: Market Expansion (Months 6-12) — Scale the Platform**
- P2: Trust portal, Google Workspace, cloud posture, phishing sim, HR integrations
- P2: CaaS packaging, vCISO dashboard, NIST 800-171
- P3: SAML SSO, DORA/NIS2, mobile auditor, marketplace SDK

---

### Completed Steps

| Step | What | Completed |
|------|------|-----------|
| 5 | Update manager Docker safety | 2026-04-05 |
| 7 | Storage provider hardening (Azure auto-create, SharePoint /teams/ + 4MB guard, Egnyte domain normalization, CSP savepoint) | 2026-04-05 |
| B1 | PDF report generation (WeasyPrint, risk register + evidence sections) | 2026-04-06 |
| A1 | Decouple Telivy from Microsoft (run_mode: telivy_only/microsoft_only/full) | 2026-04-06 |
| A2 | Job stage tracking + extended 15-min poll window | 2026-04-06 |
| A3 | Prompt adapter layer (7 model-family adapters) | 2026-04-06 |
| A4 | Wire adapters into all 10 LLM prompts + _run_chunked_llm | 2026-04-06 |
| — | NinjaOne RMM integration (full: class, routes, settings, UI tile, org mapping) | 2026-04-06 |
| — | DefensX integration (full: class, routes, settings, UI tile, customer mapping) | 2026-04-06 |
| — | Coming-soon tiles: Blackpoint Cyber, Keeper Security, SentinelOne | 2026-04-06 |

---

## Pending / Future Features

### Global Risk Dashboard (Home Page)
The Risk Register on the home screen should show ALL risks across ALL clients:
- Cross-client, cross-project view of all registered risks
- Labels per client showing which tenant the risk belongs to
- Project name shown per risk
- If a risk applies to multiple projects on same client, mark it
- Filterable by client, severity, status
- Links to the specific project's Risk Register page

### Nginx Branded Error Page
Custom 502/503/504 page at `nginx/error-pages/502.html`:
- Shows "MD Compliance — Application is starting up..." with spinner
- Auto-refreshes every 5 seconds until app responds
- Masri Digital branding
- Requires `error_page 502 503 504 /502.html` in nginx config
- Volume mounted in docker-compose.yml: `./nginx/error-pages:/usr/share/nginx/error-pages:ro`
- All nginx templates in setup.sh include the error_page directive

### Gunicorn Preload
Added `--preload` flag to gunicorn in run.sh:
- App loaded once by master process, then forked to workers
- Reduces per-worker startup time (no duplicate Flask app init)
