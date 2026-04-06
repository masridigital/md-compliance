# MD Compliance - Claude Code Reference

> **See also**: `MEMORY.md` (roadmap, technical debt, build phases) and `INTEGRATIONS.md` (integration specs, methodology, API details)

## Project Overview
Multi-tenant compliance management platform for MSPs. Pulls security data from integrations (Telivy external scans, Microsoft Entra ID, NinjaOne RMM, DefensX), maps findings to compliance framework controls via LLM, populates risk registers, and provides AI-powered remediation suggestions.

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
    ninjaone_integration.py # NinjaOne RMM API client (OAuth2)
    ninjaone_routes.py     # NinjaOne API endpoints
    defensx_integration.py # DefensX browser security API client
    defensx_routes.py      # DefensX API endpoints
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
