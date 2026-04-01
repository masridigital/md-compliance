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

## Critical Patterns & Gotchas

### Session Management
- **Boot stamp**: Each server start writes a timestamp to `ConfigStore("server_boot_stamp")`. Sessions with mismatched stamps get force-logged out.
- **Multi-worker safety**: With 2 gunicorn workers, workers booting within 30s of each other reuse the same stamp (avoids worker A writing stamp, worker B overwriting, causing instant logout).
- **Inactivity timeout**: 30 min default, uses session-only `_last_activity` timestamp. NO database access in `before_request`.

### Background Processing
- **Auto-process** (`_bg_auto_process`): Runs in a daemon thread. The `/api/v1/llm/auto-process` endpoint returns immediately, frontend polls `/api/v1/llm/auto-process-status/<tenant_id>` every 5s.
- **NEVER** run long LLM calls in the request thread — gunicorn kills workers after 120s.
- **`db.session.remove()`** at start and end of background threads to prevent session leaking.
- **DO NOT** use `session_factory` or create isolated SQLAlchemy sessions — this caused a full site crash. Use `db.session.remove()` instead.

### LLM Integration
- **Multi-provider routing**: Each feature can use a different provider+model. Config stored in `ConfigStore("llm_feature_models")` as `{sameForAll: false, models: {feature: {provider, model}}}`. Additional providers stored in `ConfigStore("llm_provider_{key}")` with encrypted API keys.
- **4-tier routing system** (not per-feature): Tier 1 (extraction) → Tier 2 (mapping) → Tier 3 (analysis) → Tier 4 (advanced). Users configure 4 dropdowns, not 11+. Features are hardcoded to tiers in `FEATURE_TIERS` dict.
- **Feature names**: `data_parsing`, `auto_map`, `assist_gaps`, `risk_score`, `control_assess`, `policy_draft`, `evidence_interpret`, `summarize`, `user_risk_profile`, `device_risk_profile`
- **Provider configs**: Primary in `SettingsLLM` table, additional in `ConfigStore("llm_additional_providers")`. Each has encrypted `api_key_enc`.
- **Chunked calls**: 10 controls per LLM call. Large frameworks (100+ controls) get multiple calls with context passing between chunks.
- **90s timeout** on all LLM provider API calls.
- **JSON extraction**: LLM responses often contain markdown/text around JSON. Use brace-matching extraction (find `{`, match nested braces, parse).
- **Status mapping**: LLM returns `compliant|partial|non_compliant`. Map to ProjectControl statuses: `complete|ready for auditor|infosec action`.
- **Progress update**: When mapping controls, also update `subcontrol.implemented` (compliant=100, partial=50, non_compliant=25) + `_sync_project_progress()` for all controls — this drives the progress bar.

### Telivy Integration
- **API key retrieval chain**: DB `SettingsStorage` → raw SQL fallback → env var `TELIVY_API_KEY`
- **Class name**: `TelivyIntegration` (NOT `TelivyClient`)
- **Scan mappings**: Stored in `ConfigStore("telivy_scan_mappings")` as JSON. Two formats: string (old: `{scan_id: tenant_id}`) and dict (new: `{scan_id: {tenant_id, type, org, score, ...}}`). Always handle both.
- **Findings method**: `get_external_scan_findings(scan_id)` (NOT `get_scan_findings`)
- **Cached data**: Auto-process stores results in `ConfigStore("tenant_integration_data_{tenant_id}")`. The integration data endpoint reads from this cache as fallback when live API calls fail.
- **Reports**: `?inline=true` param serves PDF inline (for in-app viewer), without it forces download.

### Entra ID Integration
- **Class name**: `EntraIntegration` (NOT `EntraClient`)
- **Credentials**: `SettingsEntra` model with `entra_tenant_id_enc`, `entra_client_id_enc`, `entra_client_secret_enc`
- **Platform-level**: `tenant_id=None` means platform-wide config (not per-tenant)

### Rate Limiting
- Default: 2000/day, 500/hour (was 200/50 — caused site lockout during debugging)
- Uses in-memory storage by default (`memory://`), Redis when `RATELIMIT_STORAGE_URI` set
- Container restart resets in-memory counters
- **429 errors** have a dedicated handler showing "Too many requests" (not generic "Something went wrong")
- Individual endpoints have stricter limits (e.g., LLM: 5/min, auth: 10/min)

### Error Handling
- **Catch-all** `@app.errorhandler(Exception)` renders error template, never raw tracebacks
- **SQLAlchemy errors** detected for missing columns → suggests `flask db upgrade`
- **In-app log viewer**: System page has real-time log viewer. `BufferHandler` (`app/masri/log_buffer.py`) captures last 500 entries in a ring buffer. API: `GET /api/v1/settings/system-logs`.
- **Logout** wrapped in try/except — `Logs.add()` failure cannot crash logout

### Database Migrations
- Auto-column creation at boot (`_ensure_db_columns`) for: `totp_secret_enc`, `totp_enabled`, `session_timeout_minutes`, `client_id` (mcp_api_keys), `archived` (tenants)
- Migration files in `migrations/versions/`. Known issue: `0002_masri_additions.py` has singular table references (`tenant.id` instead of `tenants.id`) — works on existing DBs but fails on fresh installs.

## Auto-Process Pipeline (Integration → LLM → Evidence → Risks)

### Complete Data Flow
```
1. User maps scan to client on Integrations page (or Re-run triggers)
2. POST /api/v1/llm/auto-process → returns immediately, spawns daemon thread
3. _bg_auto_process() runs in background:
   a. Pull Telivy data (scan details + findings via TelivyIntegration)
   b. Pull Entra data (users, MFA, compliance via EntraIntegration)
   c. Store raw data in ConfigStore("tenant_integration_data_{tenant_id}")
   d. For each project in tenant:
      - Load all ProjectControls
      - Chunk into groups of 10
      - For each chunk: compress data → send to LLM → parse JSON response
      - Apply mappings: update notes, review_status, subcontrol.implemented
      - Generate evidence: create ProjectEvidence with exhibit references
      - Add risks: create RiskRegister entries with title_hash dedup
      - Sync progress: _sync_project_progress() updates all subcontrols
   e. Store result in ConfigStore("auto_process_result_{tenant_id}")
4. Frontend polls GET /auto-process-status/{tenant_id} every 5s
5. Progress bar, Risk Register, Evidence tab all update automatically
```

### Evidence Generation Rules
- **Three tiers**: Complete (scan confirms compliance), Partial (data available, needs review), Draft (insufficient data)
- **Never fabricates evidence** — only records what the scan actually found
- **Exhibit references**: Lists specific documents needed (e.g., "Exhibit A: Telivy scan report", "Exhibit B: Screenshot of MFA policy")
- **Context-specific**: MFA findings add Entra ID exhibit, encryption findings add BitLocker exhibit
- **Fully editable**: Users modify description, add/remove exhibits, upload supporting documents

### LLM Prompt Pattern for Control Mapping
```
System: Expert compliance analyst for {framework_name}
- MUST respond with ONLY valid JSON
- MAP findings to controls with project_control_id
- CREATE risks with affected assets, IPs, users, remediation steps
- Include specific details from scan data

User: Framework + scan results (compressed) + control list (chunked)

Response: {"mappings": [...], "risks": [...]}
```

## File Structure (Key Files)
```
app/
  __init__.py              # App factory, startup tasks, error handlers
  models.py                # Core models (5000+ lines)
  masri/
    llm_routes.py          # LLM endpoints + auto-process + background worker
    llm_service.py         # Multi-provider LLM abstraction
    settings_routes.py     # All settings API endpoints
    settings_service.py    # Settings business logic + encryption
    telivy_integration.py  # Telivy API client
    telivy_routes.py       # Telivy API endpoints
    entra_integration.py   # Microsoft Entra ID client
    entra_routes.py        # Entra API endpoints
    mcp_server.py          # MCP OAuth server for Claude/ChatGPT
    scheduler.py           # Background scheduler (threading.Timer)
    new_models.py          # Masri-specific models (LLM, Entra, MCP, SSO)
    log_buffer.py          # Ring buffer for in-app log viewer
    schemas.py             # Marshmallow validation schemas
  templates/
    integrations.html      # Unified integrations page (Telivy, Entra, LLM, etc.)
    view_project.html      # Project detail page (controls, risks, integrations)
    workspace.html         # Client/tenant management
    system_info.html       # System page with log viewer
  utils/
    mixin_models.py        # ControlMixin, SubControlMixin (progress calculation)
```

## Development Commands

### Docker
```bash
docker-compose up -d --build          # Build and start
docker-compose restart app            # Restart app (resets rate limits)
docker-compose logs --tail 50 app     # View recent logs
docker-compose logs -f app 2>&1 | grep -A 5 "ERROR\|Traceback"  # Live error monitoring
```

### Git (from server)
```bash
cd /opt/NinjaRMMAgent/programfiles/md-compliance
git pull origin main
docker-compose up -d --build
```

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| "Unexpected error occurred" after login | Boot stamp mismatch between gunicorn workers | Fixed: workers within 30s reuse same stamp |
| "Unexpected error occurred" on auto-process | Gunicorn 120s timeout kills the worker | Fixed: auto-process runs in background thread |
| Site completely down, all pages error | Rate limit exhausted (was 50/hr) | `docker-compose restart app` to reset counters |
| 0% progress bar despite mapped controls | `subcontrol.implemented` not updated | Fixed: auto-process now updates subcontrols |
| AI Suggest Fixes returns 0 results | Gap filter checked wrong status values | Fixed: now checks against actual `["infosec action"]` |
| Risks not on Risk Register page | Missing `project_id` on auto-created risks | Fixed: now includes `project_id=project.id` |
| Entra data never collected | Wrong import `EntraClient` (class is `EntraIntegration`) | Fixed |
| Telivy findings empty | Wrong method `get_scan_findings` (should be `get_external_scan_findings`) | Fixed |
| LLM JSON parse failures | Regex-based extraction too strict | Fixed: brace-matching parser |

## User & Device Risk Profiles

### Risk Profile Engine (`app/masri/risk_profiles.py`)
- **`compute_risk_profiles(microsoft_data)`** — Single entry point, returns `{users, devices, summary}`
- Stored in `ConfigStore("risk_profiles_{tenant_id}")` as cached JSON
- Computed during auto-process and daily scheduler refresh

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

## Things to NEVER Do
1. **NEVER** create isolated SQLAlchemy sessions in background threads (caused full site crash)
2. **NEVER** use `dict | None` type hints (PEP 604) — may crash on older Python
3. **NEVER** access the database in `before_request` — use session-only data
4. **NEVER** run synchronous LLM calls in the request thread (120s gunicorn timeout)
5. **NEVER** set default rate limits below 500/hour (causes lockout during active development)
6. **NEVER** reference `slot` or `label` columns on `SettingsLLM` — they don't exist in the DB
