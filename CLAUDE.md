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
- **`_bg_auto_process`**: Daemon thread, returns immediately, polls via `/auto-process-status/`
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

## Things to NEVER Do
1. **NEVER** create isolated SQLAlchemy sessions in background threads (caused full site crash)
2. **NEVER** use `dict | None` type hints (PEP 604) — may crash on older Python
3. **NEVER** access the database in `before_request` — use session-only data
4. **NEVER** run synchronous LLM calls in the request thread (120s gunicorn timeout)
5. **NEVER** set default rate limits below 500/hour (causes lockout during active development)
6. **NEVER** reference `slot` or `label` columns on `SettingsLLM` — they don't exist in the DB
7. **NEVER** call external APIs (Graph, Telivy) on page load — always read from ConfigStore cache
8. **NEVER** send raw JSON dumps to LLM — always use `_compress_for_llm()` for token efficiency
9. **NEVER** create a single LLM prompt for multiple data sources — each source gets its own phase
