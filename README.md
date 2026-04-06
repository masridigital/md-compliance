# MD Compliance

**Multi-tenant compliance management platform for MSPs** — built by [Masri Digital](https://masridigital.com).

Automatically pulls security data from integrations (Telivy, Microsoft 365), maps findings to compliance framework controls via AI, populates risk registers, generates evidence, computes user/device risk profiles, and provides AI-powered remediation recommendations.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **AI-Powered Compliance** | 3-phase LLM analysis: per-integration analysis + cross-source correlation. Auto-maps findings to controls, creates risks, generates evidence. Decoupled run modes (Telivy-only, Microsoft-only, or full). |
| **Multi-Provider LLM** | 4-tier routing (extraction → mapping → analysis → advanced). Together AI, Anthropic, OpenAI, Azure. Prompt adapter layer auto-tunes prompts per model family (Claude, Llama, DeepSeek, Qwen, Gemma, Kimi). Weekly AI model recommendation engine. |
| **Telivy Integration** | External vulnerability scans, risk assessments, breach data. In-app PDF report viewer with history. Independent re-run analysis on demand. |
| **Microsoft 365 Integration** | Secure Score, Defender alerts, Intune device compliance, MFA enrollment, Identity Protection, sign-in activity, SharePoint. Cache-first (no throttling). Independent re-pull & analyze button. |
| **User & Device Risk Profiles** | Per-user scoring (MFA, risk detections, admin status) + per-device scoring (compliance, encryption, sync). AI-generated risk narratives for high-risk items. |
| **Auto-Evidence Generation** | Creates evidence entries with exhibit references (Complete/Partial/Draft tiers). Never fabricates — only records what scans found. |
| **18 Compliance Frameworks** | FTC Safeguards (Core/Mortgage/Tax), SOC 2, NIST CSF, NIST 800-53, HIPAA, PCI DSS, CMMC, ISO 27001, NY DFS, MA 201 CMR, and more. |
| **WISP Wizard** | Guided wizard for Written Information Security Programs with AI assistance and PDF/DOCX export. |
| **Background Processing** | All heavy LLM work runs in daemon threads with real-time stage tracking (collecting → analyzing → generating evidence → done). 15-minute poll window. Processing continues when user navigates away or logs out. |
| **PDF Reports** | Generate compliance reports as PDF via WeasyPrint. Includes cover page, project metrics, control status, review summary, risk register, and evidence inventory. |
| **Storage Routing** | Role-based storage (evidence/reports/backups) across Local, S3, Azure Blob, SharePoint, Egnyte. Automatic fallback to local. |
| **MCP Server** | OAuth 2.0 Model Context Protocol at `/mcp` for Claude/ChatGPT integration with 11 compliance tools. |
| **Real-time Log Viewer** | System page with live application logs, level filtering, auto-refresh, sensitive data redaction. |
| **Multi-tenancy** | Full tenant isolation with per-tenant data, projects, controls, evidence, and risk registers. |
| **SSO / 2FA** | Google + Microsoft OAuth, local auth with TOTP 2FA. |

---

## Quick Start

### Prerequisites

- Linux server with Docker and Docker Compose
- Domain pointed at your server (e.g., `compliance.yourdomain.com`)
- Ports 80 and 443 open

### Deploy

```bash
git clone https://github.com/masridigital/md-compliance.git
cd md-compliance
chmod +x setup.sh
./setup.sh
```

The setup wizard configures SSL, generates your `.env`, sets up the database, and starts the app.

### First Login

| Field | Value |
|-------|-------|
| URL | `https://your-domain.com` |
| Email | The admin email from setup |
| Password | The password from setup |

See [`SETUP.md`](SETUP.md) for full deployment details.

---

## Architecture

```
md-compliance/
├── app/
│   ├── __init__.py                 # App factory, startup, error handlers
│   ├── models.py                   # Core models (5000+ lines)
│   ├── masri/
│   │   ├── llm_routes.py           # LLM endpoints + 3-phase auto-process
│   │   ├── llm_service.py          # Multi-provider LLM + 4-tier routing
│   │   ├── prompt_adapters.py      # Per-model-family prompt adaptation layer
│   │   ├── entra_integration.py    # Microsoft 365 (Defender, Intune, Entra)
│   │   ├── telivy_integration.py   # Telivy external vulnerability scanning
│   │   ├── ninjaone_integration.py # NinjaOne RMM (endpoint management)
│   │   ├── defensx_integration.py  # DefensX (browser security)
│   │   ├── risk_profiles.py        # User & device risk scoring engine
│   │   ├── model_recommender.py    # Weekly AI model recommendation engine
│   │   ├── storage_router.py       # Role-based storage routing + fallback
│   │   ├── storage_providers.py    # S3, Azure Blob, SharePoint, Egnyte, Local
│   │   ├── mcp_server.py           # MCP OAuth server for AI assistants
│   │   ├── scheduler.py            # Background jobs (daily refresh, weekly recs)
│   │   ├── log_buffer.py           # In-app log viewer with redaction
│   │   ├── settings_routes.py      # All settings API endpoints
│   │   ├── settings_service.py     # Encryption + settings business logic
│   │   ├── notification_engine.py  # Teams, Slack, Email, SMS dispatcher
│   │   └── wisp_routes.py          # WISP wizard + PDF/DOCX export
│   ├── templates/
│   │   ├── integrations.html       # Unified integrations page
│   │   ├── view_project.html       # Project detail (controls, risks, evidence)
│   │   ├── workspace.html          # Client/tenant management
│   │   └── system_info.html        # System page + log viewer
│   └── auth/                       # OAuth, local auth, TOTP 2FA
├── docker-compose.yml              # App + Postgres + Redis + Nginx + Certbot
├── Dockerfile                      # Multi-stage Python 3.12 build
├── CLAUDE.md                       # AI development reference
├── SETUP.md                        # Full deployment guide
└── run.sh                          # Gunicorn entrypoint with DB migrations
```

---

## Integration Pipeline

```
1. Map scan to client (Telivy) or configure Entra ID (Microsoft)
2. Auto-process pulls data from configured integrations
   - run_mode: telivy_only | microsoft_only | full
   - Real-time stage tracking via polling API
3. 3-phase LLM analysis (prompts auto-tuned per model family):
   Phase 1: Telivy-only (external vulnerabilities)
   Phase 2: Microsoft-only (internal security posture)
   Phase 3: Cross-source correlation (both sources)
4. Controls mapped with status + evidence auto-generated
5. Risks created in Risk Register with dedup
6. User & device risk profiles computed
7. Progress bar updates automatically
8. Daily scheduler refreshes all data every 24 hours
```

### Supported Integrations
| Integration | Type | Status |
|-------------|------|--------|
| **Telivy** | External vulnerability scanning | Active |
| **Microsoft 365** | Entra ID + Defender + Intune | Active |
| **NinjaOne RMM** | Endpoint management | Active |
| **DefensX** | Browser security | Active |
| **Blackpoint Cyber** | MDR/SOC | Coming Soon |
| **Keeper Security** | Password management | Coming Soon |
| **SentinelOne** | EDR | Coming Soon |

---

## API Endpoints

### LLM / Auto-Process
```
POST /api/v1/llm/auto-process           Background integration processing
GET  /api/v1/llm/auto-process-status/:id Poll for results
POST /api/v1/llm/assist-gaps             AI gap analysis (background)
GET  /api/v1/llm/assist-gaps-status/:id  Poll for recommendations
POST /api/v1/llm/control-assist          Control assessment
POST /api/v1/llm/gap-narrative           Gap analysis narrative
POST /api/v1/llm/risk-score              Risk scoring
POST /api/v1/llm/refresh-microsoft/:id   Manual Microsoft data refresh
GET  /api/v1/llm/integration-data/:id    Cached integration data for project
```

### Telivy
```
POST /api/v1/telivy/test                              Test connection
GET  /api/v1/telivy/external-scans                    List external scans
POST /api/v1/telivy/external-scans                    Create new scan
GET  /api/v1/telivy/external-scans/:id                Scan details
GET  /api/v1/telivy/external-scans/:id/findings       Scan findings
GET  /api/v1/telivy/external-scans/:id/breach-data    Breach data
GET  /api/v1/telivy/external-scans/:id/report         PDF/DOCX report
GET  /api/v1/telivy/risk-assessments                  List assessments
POST /api/v1/telivy/risk-assessments                  Create assessment
GET  /api/v1/telivy/risk-assessments/:id              Assessment details
GET  /api/v1/telivy/risk-assessments/:id/devices      Device inventory
GET  /api/v1/telivy/risk-assessments/:id/scan-status  Scan completion status
GET  /api/v1/telivy/risk-assessments/:id/report       Assessment report
```

### Entra ID / Microsoft 365
```
POST /api/v1/entra/test                     Test Graph API connection
GET  /api/v1/entra/users                    Directory users
GET  /api/v1/entra/mfa-status               MFA enrollment report
POST /api/v1/entra/assess                   Compliance posture assessment
GET  /api/v1/entra/csp-clients              CSP/partner managed tenants
```

### NinjaOne RMM
```
POST /api/v1/ninjaone/test                   Test connection
GET  /api/v1/ninjaone/organizations          List organizations
GET  /api/v1/ninjaone/devices                Devices by organization
GET  /api/v1/ninjaone/alerts                 Active alerts
```

### DefensX
```
POST /api/v1/defensx/test                    Test connection
GET  /api/v1/defensx/customers               List customers
GET  /api/v1/defensx/agents/:id              Agent status by customer
GET  /api/v1/defensx/policies/:id            Web policies by customer
```

### Settings
```
GET/PUT /api/v1/settings/llm             LLM provider config
GET/PUT /api/v1/settings/llm/features    Tier-based model routing
GET     /api/v1/settings/llm/providers   All configured providers
PUT     /api/v1/settings/llm/providers/:key  Add/update provider
POST    /api/v1/settings/llm/recommendations/refresh  AI model research
GET/PUT /api/v1/settings/storage/roles   Storage role assignments
GET     /api/v1/settings/system-logs     Real-time application logs
```

### MCP Server
```
GET  /mcp/.well-known/oauth-authorization-server  OAuth discovery
POST /mcp/token                          Client credentials token
POST /mcp/tools/:name                    Execute compliance tool
```

---

## Deployment Commands

```bash
# Build and start
docker-compose up -d --build

# Restart (resets rate limits)
docker-compose restart app

# View logs
docker-compose logs --tail 50 app

# Live error monitoring
docker-compose logs -f app 2>&1 | grep -A 5 "ERROR\|Traceback"

# Update from git
cd /opt/NinjaRMMAgent/programfiles/md-compliance
git pull origin main
docker-compose up -d --build
```

---

## Tech Stack

- **Backend**: Flask 2.3.3, SQLAlchemy 2.x, PostgreSQL 16, Gunicorn
- **Frontend**: DaisyUI/Tailwind CSS, Alpine.js (no build step)
- **AI**: OpenAI, Anthropic, Together AI, Azure OpenAI (multi-provider)
- **Auth**: OAuth2 (Google + Microsoft), TOTP 2FA
- **Encryption**: Fernet (PBKDF2-HMAC-SHA256, 260K iterations)
- **Deployment**: Docker Compose (app + postgres + redis + nginx + certbot)

---

## Security

- All credentials encrypted at rest (Fernet)
- Tenant-level authorization on all endpoints
- Rate limiting (2000/day, 500/hour)
- Sensitive data redacted from in-app logs
- HTTPS enforced via Let's Encrypt
- Session management with boot stamp + inactivity timeout

Report vulnerabilities to **security@masridigital.com**

---

## License

Copyright (c) 2026 Masri Digital LLC. All rights reserved.

Licensed under the Commons Clause + GNU AGPL v3. See [LICENSE](LICENSE).

---

*Built and maintained by [Masri Digital](https://masridigital.com) — inquiry@masridigital.com*
