# MD Compliance - Claude Code Reference

## Project Overview
Multi-tenant compliance management platform for MSPs. Pulls security data from integrations (Telivy external scans, Microsoft Entra ID), maps findings to compliance framework controls via LLM, populates risk registers, and provides AI-powered remediation suggestions.

## Tech Stack
- **Backend**: Flask 2.3.3, SQLAlchemy 2.x, PostgreSQL 16, Gunicorn (2 workers, 120s timeout)
- **Frontend**: DaisyUI/Tailwind CSS, Alpine.js (no build step)
- **LLM**: OpenAI, Anthropic, Together AI, Azure OpenAI (multi-provider via `LLMService`)
- **Auth**: OAuth2 (Google + Microsoft SSO), local auth with TOTP 2FA
- **Encryption**: Fernet (PBKDF2-HMAC-SHA256, 260K iterations) for credentials at rest
- **Deployment**: Docker Compose (app + postgres + redis + nginx + certbot)

## Architecture

### Multi-Tenant Hierarchy
```
Tenant → Project → ProjectControl → ProjectSubControl → Evidence
                 → RiskRegister
```

### Key Blueprints
| Blueprint | Prefix | File |
|-----------|--------|------|
| `llm_bp` | `/api/v1/llm` | `app/masri/llm_routes.py` |
| `settings_bp` | `/api/v1/settings` | `app/masri/settings_routes.py` |
| `telivy_bp` | `/api/v1/telivy` | `app/masri/telivy_routes.py` |
| `entra_bp` | `/api/v1/entra` | `app/masri/entra_routes.py` |
| `ninjaone_bp` | `/api/v1/ninjaone` | `app/masri/ninjaone_routes.py` |
| `defensx_bp` | `/api/v1/defensx` | `app/masri/defensx_routes.py` |
| `mcp_bp` | `/mcp` | `app/masri/mcp_server.py` |

### Key Models
- **`SettingsLLM`** (`app/masri/new_models.py`): LLM provider config, single-row, encrypted API key
- **`SettingsEntra`** (`app/masri/new_models.py`): Entra ID credentials, encrypted at rest
- **`SettingsStorage`** (`app/masri/new_models.py`): Per-provider config (Telivy API key stored here)
- **`MCPAPIKey`** (`app/masri/new_models.py`): OAuth client credentials for MCP server
- **`ConfigStore`** (`app/models.py`): Key-value store for tenant data, scan mappings, process results
- **`ProjectControl`** (`app/models.py`): Uses `ControlMixin`, review_status valid values: `["infosec action", "ready for auditor", "complete"]`, default: `"infosec action"`
- **`ProjectSubControl`** (`app/models.py`): `implemented` field (0-100) drives the progress bar
- **`RiskRegister`** (`app/models.py`): `title` is Fernet-encrypted, `title_hash` for dedup, `risk` field valid values: `["unknown", "low", "moderate", "high", "critical"]`

### Primary Key Convention
All models use 8-char lowercase shortuuid: `default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower()`

---

## Integration Methodology (Template for ALL Integrations)

When adding any new integration, follow this exact methodology. Each integration goes through the same pipeline stages.

### Stage 1: Data Collection Layer
Every integration MUST have:
- **Client class** (`app/masri/{name}_integration.py`): API client with `_request()` helper, auth, timeouts (30s default)
- **Routes blueprint** (`app/masri/{name}_routes.py`): Flask endpoints for test, list, get, download
- **Credential storage**: Encrypted via `SettingsStorage` or dedicated model (e.g., `SettingsEntra`)
- **Credential chain**: DB → raw SQL fallback → env var (3-tier fallback)
- **collect_all_data() method**: Single method that gathers ALL data from the integration in one call
- **Cache-first reads**: Page loads NEVER call external APIs. Data refreshed only during:
  - Auto-process (Re-run button)
  - Manual refresh endpoint
  - Daily scheduler (every 24 hours)

### Stage 2: Data Storage
All integration data stored in `ConfigStore("tenant_integration_data_{tenant_id}")` as JSON:
```json
{
  "telivy": { ... raw Telivy data ... },
  "microsoft": { ... raw Microsoft data ... },
  "risk_profiles": { ... computed risk profiles ... },
  "_updated": "2026-03-31T12:00:00"
}
```
- Each integration owns its own key in the JSON (e.g., `"telivy"`, `"microsoft"`)
- New integrations add their own key — never overwrite others
- Cap: 35MB per tenant (allows full device inventories, detailed findings, risk profiles)

### Stage 3: LLM Analysis Pipeline (Multi-Phase)
Each integration gets its OWN LLM analysis phase with a strategically crafted prompt. Then a cross-source phase combines overlapping data.

**Pattern for each integration's LLM phase:**
1. Compress raw data into LLM-friendly text via `_compress_for_llm()`
2. Craft a system prompt that is SPECIFIC to that data source:
   - Name the exact data types available (e.g., "Secure Score gaps, Defender alerts, device compliance")
   - Tell the LLM what to look for in each data type
   - Instruct it to reference SPECIFIC items by name (users, devices, IPs, alert titles)
3. Run chunked analysis: 10 controls per LLM call via `_run_chunked_llm()`
4. Context passing: batch 1 gets full data, subsequent batches get summary of previous findings

**Multi-phase execution order in `_bg_auto_process`:**
```
Phase 1: Integration A only (e.g., Telivy — external vulns)
Phase 2: Integration B only (e.g., Microsoft — internal security)
Phase N: Integration N only (each future integration gets its own phase)
Cross:   Combined analysis (only for controls where multiple sources have relevant data)
```

**Cross-source analysis rules:**
- Only runs when 2+ integrations provide data
- Only analyzes controls NOT already mapped as non_compliant
- Prompt specifically tells the LLM to correlate data from named sources
- Examples: email security (Telivy SPF + Microsoft Exchange), auth (breach data + MFA), encryption (SSL + BitLocker)

### Stage 4: Control Mapping + Evidence + Risks
After LLM returns JSON `{mappings, risks}`:
1. **Control mapping**: Update `ProjectControl.review_status` + `notes` with `[Auto-Mapped]` prefix
2. **Subcontrol progress**: Update `ProjectSubControl.implemented` (compliant=100%, partial=50%, non_compliant=25%)
3. **Evidence generation**: Create `ProjectEvidence` with:
   - Three tiers: Complete / Partial / Draft (never fabricate — only record what scan found)
   - Exhibit references specific to the data source
   - Linked to applicable subcontrols via `EvidenceAssociation`
4. **Risk creation**: Create `RiskRegister` entries with `title_hash` dedup + `project_id`
5. **Progress sync**: `_sync_project_progress()` backfills all subcontrols + evidence

### Stage 5: Risk Profile Computation
After all integration data is collected:
1. `compute_risk_profiles(microsoft_data)` generates per-user and per-device scores
2. `generate_risk_narratives(profiles)` uses Tier 4 LLM for high-risk items (score >= 50)
3. Stored in ConfigStore alongside integration data
4. Displayed on project integrations tab

### Stage 6: UI Display
Each integration appears as a card on the project integrations tab:
- Summary stats row (4 boxes with key metrics)
- Clickable header to expand/collapse
- Expandable detail items with severity badges
- All data read from ConfigStore cache — no live API calls

### Adding a New Integration Checklist
When adding integration "X":
- [ ] Create `app/masri/x_integration.py` with API client class
- [ ] Create `app/masri/x_routes.py` with Flask blueprint
- [ ] Add credential storage (model or ConfigStore)
- [ ] Add `collect_all_data()` method
- [ ] Add data pull to `_bg_auto_process()` under key `"x"`
- [ ] Add `_compress_for_llm()` section for "x" data
- [ ] Add LLM Phase N with source-specific system prompt
- [ ] Update cross-source phase to include "x" correlations
- [ ] Add risk profile contributions (if applicable)
- [ ] Add UI card to `view_project.html` integrations tab
- [ ] Add settings tile to `integrations.html`
- [ ] Add to daily scheduler refresh
- [ ] Update this CLAUDE.md with integration-specific notes
- [ ] Add required permissions/setup guide to the settings tile

---

## Current Integrations

### Integration 1: Telivy (External Vulnerability Scanning)
- **Client**: `TelivyIntegration` in `telivy_integration.py` (NOT `TelivyClient`)
- **Auth**: API key via `x-api-key` header
- **Credential chain**: DB `SettingsStorage` → raw SQL fallback → env var `TELIVY_API_KEY`
- **Data collected**: External scans, findings, risk assessments, breach data
- **Key methods**: `get_external_scan_findings(scan_id)` (NOT `get_scan_findings`), `list_external_scans()`, `get_risk_assessment()`
- **Scan mappings**: `ConfigStore("telivy_scan_mappings")` — two formats: string `{scan_id: tenant_id}` and dict `{scan_id: {tenant_id, type, org, ...}}`
- **Reports**: `?inline=true` serves PDF inline for in-app viewer
- **LLM prompt focus**: External vulnerabilities — network exposure, DNS, email spoofing, SSL/TLS, web app flaws, typosquatting, breach data

### Integration 2: Microsoft 365 (Entra ID + Defender + Intune)
- **Client**: `EntraIntegration` in `entra_integration.py` (NOT `EntraClient`)
- **Auth**: MSAL client credentials flow (OAuth 2.0)
- **Credential storage**: `SettingsEntra` model with `entra_tenant_id_enc`, `entra_client_id_enc`, `entra_client_secret_enc`
- **Platform-level**: `tenant_id=None` means platform-wide config
- **Single collection method**: `collect_all_security_data()` pulls everything
- **Data collected**:
  - Users + MFA enrollment status
  - Secure Score (overall + gap controls)
  - Defender security alerts + incidents
  - Intune managed devices (compliance, encryption)
  - Identity Protection risky users + risk detections
  - Sign-in activity (failures, anomalies, locations)
  - Conditional Access policies
  - SharePoint sites
- **Cache-first**: Page loads NEVER call Graph API — prevents throttling
- **LLM prompt focus**: Internal security posture — Secure Score gaps, Defender alerts, device compliance/encryption, MFA gaps, risky users by name, sign-in anomalies

#### Microsoft Graph API Permissions Required
Register an Azure AD App with these **Application** permissions:

| Endpoint | Permission | Used For |
|----------|-----------|----------|
| `/users` | `User.Read.All` | User inventory, account status |
| `/reports/authenticationMethods/userRegistrationDetails` | `UserAuthenticationMethod.Read.All` | MFA enrollment |
| `/identity/conditionalAccess/policies` | `Policy.Read.All` | Conditional Access audit |
| `/security/alerts_v2` | `SecurityAlert.Read.All` | Defender alerts |
| `/security/secureScores` | `SecurityEvents.Read.All` | Secure Score |
| `/security/incidents` | `SecurityIncident.Read.All` | Security incidents |
| `/deviceManagement/managedDevices` | `DeviceManagementManagedDevices.Read.All` | Intune devices |
| `/identityProtection/riskyUsers` | `IdentityRiskEvent.Read.All` | Risky users |
| `/identityProtection/riskDetections` | `IdentityRiskEvent.Read.All` | Risk events |
| `/auditLogs/signIns` | `AuditLog.Read.All` | Sign-in logs |
| `/sites` | `Sites.Read.All` | SharePoint sites |
| `/organization` | `Organization.Read.All` | Org profile |

### Integration 3: NinjaOne RMM (Endpoint Management)
- **Client**: `NinjaOneIntegration` in `ninjaone_integration.py`
- **Auth**: OAuth2 Client Credentials (client_id + client_secret, scope: `monitoring`)
- **Token endpoint**: `{instance_url}/oauth/token` (NOT under `/v2/`)
- **Region-specific base URLs**: US (`app.ninjarmm.com`), EU (`eu.ninjarmm.com`), AP (`app.ninjarmm.com.au`), CA (`ca.ninjarmm.com`)
- **API prefix**: `/v2/`
- **Credential storage**: `SettingsStorage` with `provider="ninjaone"`, encrypted config containing `client_id`, `client_secret`, `region`
- **Credential chain**: DB SettingsStorage → env vars `NINJAONE_CLIENT_ID` / `NINJAONE_CLIENT_SECRET` / `NINJAONE_REGION`
- **Org mappings**: `ConfigStore("ninjaone_org_mappings")` — JSON: `{org_id: {tenant_id, org_name}}`
- **Multi-tenant**: Single MSP-level OAuth app sees all client organizations. Devices scoped via `organizationId`.
- **Data collected**: devices (detailed), OS patches, software patches, AV status, AV threats, alerts, activities, organizations
- **Key bulk endpoints**: `/v2/queries/os-patches`, `/v2/queries/antivirus-status` (prefer over per-device calls)
- **Pagination**: Cursor-based (`pageSize` + `after` params), safety cap 5000
- **LLM prompt focus**: Endpoint compliance — patch status, AV coverage, encryption enforcement, stale devices, OS currency

### Integration 4: DefensX (Browser Security)
- **Client**: `DefensXIntegration` in `defensx_integration.py`
- **Auth**: Bearer token (`Authorization: Bearer {api_token}`)
- **Base URL**: `https://cloud.defensx.com/api/partner/v1`
- **NOTE**: DefensX does not publish a public API reference. Endpoint paths are per integration spec — may need adjustment once API access is confirmed with DefensX partner support.
- **Credential storage**: `SettingsStorage` with `provider="defensx"`, encrypted config containing `api_token`
- **Credential chain**: DB SettingsStorage → env var `DEFENSX_API_TOKEN`
- **Customer mappings**: `ConfigStore("defensx_customer_mappings")` — JSON: `{customer_id: {tenant_id, customer_name}}`
- **Multi-tenant**: Single partner token accesses all customer tenants
- **Data collected**: agent deployment status, web policy compliance, cyber resilience scores, user activity, shadow AI detection, security logs (URL visits, DNS queries, credential events, file transfers)
- **LLM prompt focus**: Browser-layer controls — web filtering, credential protection, shadow AI, DLP

### Coming Soon Integrations (Tiles Only — No Backend)
- **Blackpoint Cyber** (`ti-shield-bolt`): MDR/SOC detections, endpoint inventory, vulnerability scanning, dark web monitoring, NIST-aligned security posture rating. CompassOne HTTP Export API.
- **Keeper Security** (`ti-lock`): Password health audits, 2FA enrollment, BreachWatch dark web monitoring, PAM session logs. Admin REST API + MSP Account Management API.
- **SentinelOne** (`ti-sword`): EDR agent coverage, threat detection/mitigation, policy enforcement, endpoint compliance. Management Console REST API v2.1 with `ApiToken` auth.

---

## LLM Configuration

### 4-Tier Routing System
Users configure 4 tiers (not 11+ individual features). Features are hardcoded to tiers in `FEATURE_TIERS` dict.

| Tier | Features | Recommended Provider | Why |
|------|----------|---------------------|-----|
| **1: Extraction** | `data_parsing`, `summarize`, `evidence_interpret` | Together AI (cheap model) | High-volume structured parsing |
| **2: Mapping** | `auto_map`, `control_assess`, `risk_score` | Together AI (larger model) | Needs good JSON + domain knowledge |
| **3: Analysis** | `assist_gaps`, `gap_narrative` | Claude Sonnet | Reasoning for recommendations |
| **4: Advanced** | `policy_draft`, `user_risk_profile`, `device_risk_profile` | Claude Opus | Nuanced long-form + risk narratives |

### Multi-Provider Config
- **Primary**: `SettingsLLM` table
- **Additional**: `ConfigStore("llm_additional_providers")` with encrypted API keys per provider
- **Tier config**: `ConfigStore("llm_feature_models")` as `{sameForAll: false, tiers: {extraction: {provider, model}, ...}}`
- **90s timeout** on all provider API calls
- **JSON extraction**: Brace-matching parser (find `{`, match nested braces, parse)

---

## User & Device Risk Profiles

### Risk Profile Engine (`app/masri/risk_profiles.py`)
- **`compute_risk_profiles(microsoft_data)`** — Returns `{users, devices, summary}`
- **`generate_risk_narratives(profiles)`** — Tier 4 LLM for high-risk items (score >= 50)
- Stored in `ConfigStore("tenant_integration_data_{tenant_id}")` under `"risk_profiles"` key
- Computed during auto-process when Microsoft data is available

### User Risk Scoring (0-100)
| Factor | Points | Notes |
|--------|--------|-------|
| No MFA | +30 | Biggest single factor |
| Identity Protection high risk | +40 | From `riskyUsers` API |
| Identity Protection medium/low | +25 | Flagged but not critical |
| Risk detections | +5 each (max 3) | Specific incidents with IPs |
| Non-compliant device | +15 per device (max 3) | Cross-linked from device profiles |
| Disabled account | +5 | Exists but disabled |
| Admin role | 1.5x multiplier | Admins weighted higher |
| Shared mailbox | -20 | Non-interactive, reduced risk |

### Device Risk Scoring (0-100)
| Factor | Points | Notes |
|--------|--------|-------|
| Non-compliant | +35 | Fails Intune policy |
| Unencrypted | +30 | No BitLocker/FileVault |
| Stale sync (14+ days) | +12 | Not checking in |
| Stale sync (30+ days) | +17 | Very stale |
| Server | 1.3x multiplier | Higher value target |
| Assigned to risky user | +10 | Cross-linked from user profiles |

### Risk Levels
- **Critical** (70-100): Immediate action required
- **High** (50-69): Action needed within 1 week
- **Medium** (25-49): Review within 1 month
- **Low** (0-24): Acceptable risk

---

## Critical Patterns & Gotchas

### Session Management
- **Boot stamp**: Workers within 30s reuse same stamp (multi-worker safe)
- **Inactivity timeout**: 30 min, session-only `_last_activity`. NO database in `before_request`.

### Background Processing
- **`_bg_auto_process`**: Daemon thread, returns immediately, polls via `/auto-process-status/`, supports `run_mode` (telivy_only | microsoft_only | full)
- **Job stages**: `_update_job_status()` writes to ConfigStore, frontend polls for stage + chunk progress
- **`db.session.remove()`** at start/end of background threads
- **NEVER** use `session_factory` — caused full site crash

### Rate Limiting
- Default: 2000/day, 500/hour. Container restart resets counters.
- **429 handler** shows "Too many requests" (not generic error)

### Error Handling
- Catch-all renders error template, never raw tracebacks
- In-app log viewer: System page, `BufferHandler` ring buffer (500 entries)
- Logout wrapped in try/except

---

## File Structure
```
app/
  __init__.py              # App factory, startup tasks, error handlers
  models.py                # Core models (5000+ lines)
  masri/
    llm_routes.py          # LLM endpoints + auto-process + 3-phase analysis
    llm_service.py         # Multi-provider LLM abstraction + 4-tier routing
    settings_routes.py     # All settings API endpoints
    settings_service.py    # Settings business logic + encryption
    telivy_integration.py  # Telivy API client
    telivy_routes.py       # Telivy API endpoints
    entra_integration.py   # Microsoft Entra ID + Defender + Intune client
    entra_routes.py        # Entra API endpoints
    ninjaone_integration.py # NinjaOne RMM API client (OAuth2)
    ninjaone_routes.py     # NinjaOne API endpoints
    defensx_integration.py # DefensX browser security API client
    defensx_routes.py      # DefensX API endpoints
    prompt_adapters.py     # Model-family-specific prompt adapter layer
    risk_profiles.py       # User & device risk profile engine
    mcp_server.py          # MCP OAuth server for Claude/ChatGPT
    scheduler.py           # Background scheduler (threading.Timer)
    new_models.py          # Masri-specific models (LLM, Entra, MCP, SSO)
    log_buffer.py          # Ring buffer for in-app log viewer
    schemas.py             # Marshmallow validation schemas
  templates/
    integrations.html      # Unified integrations page
    view_project.html      # Project detail (controls, risks, integrations, risk profiles)
    workspace.html         # Client/tenant management
    system_info.html       # System page with log viewer
```

---

## Development Commands

```bash
# Docker
docker-compose up -d --build          # Build and start
docker-compose restart app            # Restart (resets rate limits)
docker-compose logs --tail 50 app     # Recent logs
docker-compose logs -f app 2>&1 | grep -A 5 "ERROR\|Traceback"  # Live errors

# Server deploy
cd /opt/NinjaRMMAgent/programfiles/md-compliance
git pull origin main
docker-compose up -d --build
```

---

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| "Unexpected error" after login | Boot stamp mismatch between workers | Workers within 30s reuse same stamp |
| "Unexpected error" on auto-process | Gunicorn 120s timeout | Auto-process runs in background thread |
| Site completely down | Rate limit exhausted | `docker-compose restart app` |
| 0% progress bar | `subcontrol.implemented` not updated | Auto-process now updates subcontrols |
| AI Suggest Fixes returns 0 | Gap filter wrong status values | Checks `["infosec action"]` |
| Risks not on Risk Register page | Missing `project_id` | Now includes `project_id=project.id` |
| Entra data never collected | Wrong import `EntraClient` | Class is `EntraIntegration` |
| Telivy findings empty | Wrong method name | `get_external_scan_findings` not `get_scan_findings` |
| Microsoft data missing on page load | Live API calls on every load | Cache-first: reads from ConfigStore |
| Risk profiles not showing | Auto-process not re-run since feature added | Re-run triggers computation |

## Storage System

### Storage Router (`app/masri/storage_router.py`)
Routes file operations to the correct provider based on role assignments.

**Roles:**
- `evidence` — User-uploaded evidence files (screenshots, docs, configs)
- `reports` — Generated compliance reports (WISP, audit, Telivy PDFs)
- `backups` — Integration data snapshots, DB exports

**Priority chain (per role):**
1. Explicit role assignment in `ConfigStore("storage_role_config")`
2. Default provider (marked `is_default` in `SettingsStorage`)
3. Local filesystem (always available)

**Fallback:** If configured provider fails, automatically retries with local storage. Never loses a file.

**Providers:** Local, S3, Azure Blob, SharePoint, Egnyte (all in `storage_providers.py`)

**API endpoints:**
- `GET /api/v1/settings/storage-overview` — overview of all configured providers + role assignments
- `GET /api/v1/settings/storage-roles` — current role → provider mapping
- `PUT /api/v1/settings/storage-roles` — assign providers to roles

**IMPORTANT**: Storage sub-routes MUST NOT use `/storage/X` pattern because `/storage/<string:provider>` catches everything. Use `/storage-X` (hyphenated) instead.

**Usage:**
```python
from app.masri.storage_router import store_file, get_file, get_file_url
path = store_file(file_data, "screenshot.png", "projects/abc", role="evidence")
data = get_file(path, role="evidence")
url = get_file_url(path, role="evidence", expires_hours=24)  # Auditor access
```

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
| ~~4~~ | ~~Wire adapters into all prompts~~ | **DONE** | `llm_service.py` (auto-adapts in `LLMService.chat()`), `llm_routes.py` (chunk size) |
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
| B1 | Complete PDF report generation | `app/utils/reports.py` | High — stub raises `NotImplementedError` |
| B2 | Migrate scheduler to Celery/Redis | `app/masri/scheduler.py`, `docker-compose.yml` | High — threading.Timer unreliable in multi-worker |
| B3 | Add CI/CD pipeline | New `.github/workflows/` | High — no automated testing or deployment |
| B4 | Upgrade PCI DSS v3.1 → v4.0 | `app/files/base_controls/pci_3.1.json` | High — v3.1 deprecated March 2024 |

#### B1: PDF Report Generation
- **Current state**: `app/utils/reports.py:31` — `generate()` raises `ValueError("Not Implemented")`
- **Route exists**: `/api/v1/projects/{id}/report` returns the error
- **Implementation**: Use WeasyPrint (already referenced in imports) to render HTML templates to PDF
- **Report types**: Compliance summary, gap analysis, risk register, evidence inventory, audit-ready package
- **Template**: Jinja2 HTML → CSS → WeasyPrint PDF pipeline
- **Key data**: Project controls, subcontrol progress, evidence list, risk register, framework metadata

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

**Each new integration follows the methodology in "Integration Methodology" section above.**

#### C2: Continuous Monitoring
**Problem**: Current drift detection is passive — checks every 24h for 90-day-stale controls. No real-time configuration change detection.

**Implementation**:
- **Webhook receivers**: Accept real-time events from Entra ID (via Azure Event Hub), NinjaRMM, ConnectWise
- **Configuration baseline**: Snapshot known-good state (Conditional Access policies, MFA settings, device compliance policies)
- **Delta detection**: Compare current state to baseline on each data refresh
- **Alert on drift**: Policy removed, MFA disabled for user, compliance policy changed, new admin added
- **Dashboard widget**: "Configuration changes since last audit" with timeline
- **Scheduler upgrade**: Increase integration_refresh frequency for tenants with continuous monitoring enabled (every 4h instead of 24h)

**Files**: New `app/masri/continuous_monitor.py`, extend `scheduler.py`, new webhook blueprint

#### C3: Employee Training Module
**Problem**: 7 of 14 competitors include training. FTC Safeguards explicitly requires training documentation. Currently only a `"training"` type in `DueDate.VALID_ENTITY_TYPES` — no actual module.

**Implementation**:
- **Training model**: `Training` — id, tenant_id, title, description, content_type (video_url, document, quiz), frequency (annual, quarterly, onboarding), framework_requirements (which controls need this)
- **TrainingAssignment model**: tenant_id, training_id, user_email, assigned_date, completed_date, score, certificate_url
- **Training blueprint**: `app/masri/training_routes.py` with CRUD + assignment + completion tracking
- **Built-in content**: FTC Safeguards training template, HIPAA security awareness template, general security awareness template
- **Evidence integration**: Training completion auto-generates evidence for applicable controls
- **Reminders**: Extend scheduler with training due reminders
- **UI**: Training management page, employee completion dashboard, training assignment from control gap view

#### C4: Missing Compliance Frameworks
**Current**: 18 frameworks. **Missing high-value frameworks**:

| Framework | Why | Target Market |
|-----------|-----|---------------|
| **PCI DSS v4.0** | v3.1 deprecated, v4.0 mandatory since March 2025 | Retail, e-commerce, payment processors |
| **GDPR** | EU data protection, any company with EU customers | All companies with EU presence |
| **CCPA/CPRA** | California consumer privacy, expanding to other states | Any company with CA customers |
| **ABA Model Rules** | **Zero competitors cover this** — massive white space | Law firms (Ethics + Client Data rules) |
| **HITRUST CSF** | Healthcare-specific, maps to HIPAA + NIST | Healthcare, health tech, insurers |

**Implementation per framework**:
- Create `app/files/base_controls/{framework}.json` with control hierarchy
- Add framework metadata to framework creation flow
- Populate `Control.mapping` field with cross-references to existing frameworks
- Test auto-process LLM phases with new controls

**ABA Model Rules** (unique differentiator):
- ABA Model Rules 1.1 (Competence — technology competence), 1.4 (Communications — breach notification), 1.6 (Confidentiality — data protection), 5.1/5.3 (Supervision — employee training)
- Cross-map to NIST 800-53 and SOC 2 where applicable
- Evidence types: attorney training records, encryption policies, incident response plans, vendor due diligence

#### C5: Cross-Framework Control Mapping
**Problem**: `Control.mapping` field (`models.py:1921`, `db.Column(db.JSON(), default={})`) exists but is empty and unused.

**Implementation**:
- **Mapping data**: Populate `Control.mapping` with cross-references during framework seed:
  ```json
  {
    "nist_800_53": ["AC-2", "AC-3"],
    "soc2": ["CC6.1", "CC6.2"],
    "iso_27001": ["A.9.2.1"],
    "pci_dss_v4": ["7.1", "7.2"]
  }
  ```
- **UI**: "Related Controls" panel on control detail view showing equivalent controls in other frameworks
- **Auto-process**: When a control is mapped as compliant, suggest the same status for mapped controls in other frameworks on the same project
- **Gap analysis**: "If you comply with NIST AC-2, you also satisfy SOC 2 CC6.1" — reduces duplicate work
- **Mapping sources**: NIST SP 800-53 Rev 5 Appendix H (official NIST-to-ISO mapping), CSA CCM cross-reference, PCI DSS v4.0 mapping guide

#### C6: Trust Portal (Client-Facing Compliance Status Page)
**Problem**: No way for clients' customers or auditors to view compliance status externally without logging in.

**Implementation**:
- **Public route**: `/trust/{tenant_slug}` — unauthenticated, rate-limited
- **Displays**: Framework compliance percentage, last audit date, active certifications, security contact
- **Controls**: Tenant configures which frameworks are visible, custom branding, custom domain (CNAME)
- **Documents**: Downloadable SOC 2 report, penetration test summary (tenant uploads, controls access)
- **NDA gate**: Optional — require email + NDA acceptance before viewing detailed reports
- **API**: `/api/v1/trust/{tenant_slug}/status` for programmatic access (vendor questionnaire automation)

---

### Completed Steps

| Step | What | Completed |
|------|------|-----------|
| 5 | Update manager Docker safety | 2026-04-05 |
| 7 | Storage provider hardening (Azure auto-create, SharePoint /teams/ + 4MB guard, Egnyte domain normalization, CSP savepoint) | 2026-04-05 |
| 1 | Decouple Telivy from Microsoft (`run_mode` parameter: telivy_only / microsoft_only / full) | 2026-04-06 |
| 2 | Job stages + extended poll (15 min timeout, stage/chunk progress in UI) | 2026-04-06 |
| 3 | Prompt adapter layer (7 model-family adapters: Claude, DeepSeek, Llama, Kimi, Gemma, Qwen, Default) | 2026-04-06 |
| 4 | Wire adapters into all prompts (auto-adapts in LLMService.chat(), chunk size in _run_chunked_llm) | 2026-04-06 |
| B1 | PDF report generation with WeasyPrint | 2026-04-05 |

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

---

## Things to NEVER Do
1. **NEVER** push to main without running a security review first — use a security review agent in parallel during development, or run a full audit before the final push
2. **NEVER** create isolated SQLAlchemy sessions in background threads (caused full site crash)
3. **NEVER** use `dict | None` type hints (PEP 604) — may crash on older Python
4. **NEVER** access the database in `before_request` — use session-only data
5. **NEVER** run synchronous LLM calls in the request thread (120s gunicorn timeout)
6. **NEVER** set default rate limits below 500/hour (causes lockout during active development)
7. **NEVER** reference `slot` or `label` columns on `SettingsLLM` — they don't exist in the DB
8. **NEVER** call Microsoft Graph API on page load — always read from ConfigStore cache (throttling risk). Telivy API calls on page load are OK (no throttling).
9. **NEVER** send raw JSON dumps to LLM — always use `_compress_for_llm()` for token efficiency
10. **NEVER** create a single LLM prompt for multiple data sources — each source gets its own phase
11. **NEVER** store the same data in multiple ConfigStore keys — use ONE key per data type. Duplicate storage causes stale data and DB errors. Example: additional provider keys go in `ConfigStore("llm_additional_providers")` ONLY, not also in `ConfigStore("llm_provider_{key}")`.
12. **NEVER** send Alpine.js proxy objects directly to `JSON.stringify()` for API calls — extract plain values first. Alpine wraps objects in Proxy which can contain circular references or non-serializable data.
13. **NEVER** create Flask routes under `/storage/X` — use `/storage-X` (hyphenated) because `/storage/<string:provider>` catches everything.
14. **NEVER** use the same generic LLM prompt for all model families — always use the prompt adapter layer (`prompt_adapters.py`) to adapt prompts per model.
15. **NEVER** delete a deprecated framework JSON file — mark it deprecated, keep for legacy projects.
