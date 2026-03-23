# MD Compliance

**Security & regulatory compliance platform for Masri Digital clients.**

Manage compliance frameworks, generate WISP documents, track controls, and get AI-assisted gap analysis — all in one clean, mobile-friendly interface built for CPA firms, law firms, mortgage lenders, and financial services companies.

---

## Table of Contents

1. [Features](#features)
2. [Quick Start](#quick-start)
3. [Frameworks Included](#frameworks-included)
4. [Configuration](#configuration)
5. [API Overview](#api-overview)
6. [Architecture](#architecture)
7. [Development](#development)
8. [Deployment](#deployment)
9. [Support](#support)

---

## Features

| Feature | Description |
|---------|-------------|
| **Compliance Frameworks** | 18 built-in frameworks (FTC Safeguards, HIPAA, SOC2, NIST, PCI DSS, NY DFS, MA 201 CMR, and more) |
| **WISP Wizard** | 10-step guided wizard to create a Written Information Security Program with LLM assistance and PDF/DOCX export |
| **LLM Integration** | AI-assisted control assessment, gap narratives, evidence interpretation (OpenAI, Anthropic, Azure OpenAI, Ollama) |
| **Settings Hub** | 9-panel admin UI — SSO, LLM, Storage, Branding, Users, Notifications, Frameworks, API/MCP, Billing |
| **Storage Integrations** | Azure Blob Storage, SharePoint (Graph API), Amazon S3, Egnyte, Local |
| **Teams Webhooks** | Adaptive Card alerts with action buttons for due dates, control changes, and reminders |
| **Due Date Tracking** | Per-control due dates with automated 30d / 7d / 1d / on-due / overdue reminder delivery |
| **Entra ID / M365** | Microsoft Graph API auto-assessment — user list, MFA status, conditional access, Intune posture |
| **MCP Server** | Model Context Protocol API at `/mcp/v1` with 11 tools and API key scoped access |
| **Custom Branding** | Fully customizable logo, colors, app name, and support email from the Settings UI |
| **Mobile PWA** | Responsive design with bottom tab bar, safe area insets, offline support |
| **Multi-tenancy** | Separate tenant spaces with isolated storage containers and per-tenant settings |
| **SSO / OIDC** | Single Sign-On via OpenID Connect (configurable per tenant) |

---

## Quick Start

### Prerequisites

- A Linux server with Docker and Docker Compose installed
- A domain or subdomain pointed at your server's IP (e.g. `compliance.masridigital.com`)
- Ports 80 and 443 open

### 1. Clone the repo

```bash
git clone https://github.com/masridigital/md-compliance.git
cd md-compliance
```

### 2. Run the setup wizard

```bash
chmod +x setup.sh
./setup.sh
```

The wizard will ask for your domain name, your preferred SSL verification method (HTTP or DNS TXT record), set up a free Let's Encrypt certificate, generate your `.env`, configure nginx, and start the app automatically.

### 3. Log in

| Field | Value |
|-------|-------|
| URL | `https://your-domain.com` |
| Email | The email you entered in Step 3 of the wizard |
| Password | The password you entered in Step 3 of the wizard |

> **Change the password** via Settings → Users after first login if you used a temporary one.

See [`SETUP.md`](SETUP.md) for full details including manual configuration, integrations, and update procedures.

---

## Frameworks Included

### Financial Services & Mortgage

| Framework | Controls | Description |
|-----------|----------|-------------|
| FTC Safeguards Rule (Core) | 15 | FTC 16 CFR Part 314 core requirements |
| FTC Safeguards — Mortgage | 9 | Mortgage lender & broker specifics |
| FTC Safeguards — Tax Preparer | 6 | IRS tax preparer requirements |
| IRS Publication 4557 | 12 | Safeguarding taxpayer data |
| NY DFS 23 NYCRR 500 | 20 | NY Dept. of Financial Services cybersecurity |
| MA 201 CMR 17.00 | 10 | Massachusetts personal information protection |

### General Security

| Framework | Description |
|-----------|-------------|
| SOC 2 | Service Organization Controls |
| NIST CSF | NIST Cybersecurity Framework |
| NIST 800-53 | Federal security controls |
| CMMC | Cybersecurity Maturity Model Certification |
| HIPAA | Health data privacy & security |
| PCI DSS | Payment card industry standard |
| ISO 27001 | Information security management |
| CIS Controls v18 | Center for Internet Security top controls |
| ASVS | Application Security Verification Standard |
| SSF | Secure Software Framework |

---

## Configuration

All configuration is handled via two methods:

1. **Environment variables** (`.env` file) — infrastructure-level settings
2. **Settings UI** (Admin → Settings) — app-level settings stored in the database

### Core Environment Variables

```env
# ── App ──────────────────────────────────────────────────────────────
SECRET_KEY=change_this_to_a_long_random_string
APP_NAME=MD Compliance
APP_ENV=production            # development | production
PORT=8000

# ── Database ─────────────────────────────────────────────────────────
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=mdcompliance
POSTGRES_USER=mdcompliance
POSTGRES_PASSWORD=changeme

# ── Email ─────────────────────────────────────────────────────────────
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=notifications@masridigital.com
MAIL_PASSWORD=
MAIL_USE_TLS=true

# ── LLM (optional — also configurable in Settings UI) ────────────────
LLM_ENABLED=false

# ── Microsoft Entra ID (optional) ────────────────────────────────────
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=

# ── Notifications (optional) ─────────────────────────────────────────
TEAMS_WEBHOOK_URL=
SLACK_WEBHOOK_URL=

# ── Scheduler ────────────────────────────────────────────────────────
MASRI_SCHEDULER_ENABLED=true
```

For the full variable list, see [`.env.example`](.env.example).

### Settings UI Panels

These are configured inside the app at **Admin → Settings**:

| Panel | What You Configure |
|-------|--------------------|
| **Branding** | Logo, app name, primary color, support email |
| **SSO / OIDC** | Identity provider URL, client ID/secret, auto-provisioning |
| **LLM** | Provider (OpenAI/Anthropic/Azure/Ollama), API key, model, token budgets |
| **Storage** | Active provider, credentials, container/folder names |
| **Notifications** | Teams webhook, email, Slack, SMS; event subscriptions |
| **Users** | Add/edit/deactivate users, role assignments, API keys |
| **Frameworks** | Enable/disable frameworks per tenant |
| **API / MCP** | MCP server toggle, API key management, scope permissions |
| **Billing** | Subscription tier and usage overview |

---

## API Overview

All endpoints are under `/api/v1/` and require an `Authorization: Bearer <token>` header.

### WISP

```
POST /api/v1/wisp/assist           LLM content generation for wizard steps
POST /api/v1/wisp/generate         Generate final WISP document
POST /api/v1/wisp/<id>/export/pdf  Export branded PDF
POST /api/v1/wisp/<id>/export/docx Export branded DOCX
POST /api/v1/wisp/<id>/sign        Digital signature capture
GET  /api/v1/wisp/<id>/versions    Version history
```

### LLM

```
POST /api/v1/llm/control-assist    Control assessment assistance
POST /api/v1/llm/gap-narrative     Gap analysis narrative
POST /api/v1/llm/risk-score        Risk scoring
POST /api/v1/llm/interpret-evidence Evidence interpretation
GET  /api/v1/llm/usage             Token usage statistics
```

### Notifications

```
POST /api/v1/notifications/send          Send to any channel
POST /api/v1/notifications/test-teams    Test Teams webhook
POST /api/v1/notifications/test-email    Test email
GET  /api/v1/notifications/logs          Notification history
POST /api/v1/notifications/check-reminders Trigger reminder check
```

### Entra ID

```
POST /api/v1/entra/test     Test Graph API connection
GET  /api/v1/entra/users    List directory users
GET  /api/v1/entra/mfa-status MFA registration report
POST /api/v1/entra/assess   Run compliance posture assessment
```

### MCP Server

```
GET  /mcp/v1/tools           Discover available tools
POST /mcp/v1/tools/<name>    Execute a tool
```

---

## Architecture

```
md-compliance/
├── app/
│   ├── masri/                  # All MD Compliance additions
│   │   ├── new_models.py       # Database models
│   │   ├── settings_service.py # Encrypted settings store
│   │   ├── settings_routes.py  # Settings API
│   │   ├── llm_service.py      # Multi-provider LLM facade
│   │   ├── llm_routes.py       # LLM API
│   │   ├── mcp_server.py       # MCP protocol server
│   │   ├── wisp_routes.py      # WISP API
│   │   ├── wisp_export.py      # PDF/DOCX export
│   │   ├── notification_engine.py  # Teams/Email/Slack/SMS dispatcher
│   │   ├── notification_routes.py  # Notification API
│   │   ├── storage_providers.py    # Azure/SharePoint/S3/Egnyte/Local
│   │   ├── entra_integration.py    # Microsoft Graph API client
│   │   ├── entra_routes.py         # Entra ID API
│   │   ├── scheduler.py            # Background due-date & drift jobs
│   │   ├── context_processors.py   # Jinja2 branding injection
│   │   └── frameworks/             # New framework JSON files
│   ├── files/base_controls/    # All 18 framework definitions (JSON)
│   ├── templates/              # Jinja2 HTML templates
│   └── static/
│       ├── css/masri-design-system.css  # Apple-style design system
│       └── css/masri-mobile.css         # Mobile/PWA styles
├── .env.example                # All env vars with comments
├── docker-compose.yml
├── Dockerfile
└── SETUP.md                    # Detailed setup & deployment guide
```

---

## Development

### Run locally (without Docker)

```bash
# 1. Start only the database
docker-compose up -d postgres

# 2. Create a Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables (copy the example and fill in values)
cp .env.example .env
export $(grep -v '^#' .env | xargs)
export POSTGRES_HOST=localhost
export APP_ENV=development
export FLASK_CONFIG=development

# 5a. Fresh database — create all tables and seed the admin user
python manage.py init_db

# 5b. Existing database — apply any new migrations
flask db upgrade

# 6. Start the app
flask run --port 5000
```

### Adding a new framework

1. Create a JSON file in `app/files/base_controls/` following the existing format
2. Register it in `app/masri/frameworks/` if it needs LLM metadata
3. Run `flask db upgrade` to pick up any schema changes

### Adding a new settings panel

1. Add model fields to `app/masri/new_models.py`
2. Add service methods to `app/masri/settings_service.py`
3. Add API routes to `app/masri/settings_routes.py`
4. Add the UI panel to `app/templates/management/settings_masri.html`

---

## Deployment

See [`SETUP.md`](SETUP.md) for full production deployment instructions including:

- Environment variable checklist
- SSL/TLS setup
- Multi-worker configuration
- Disabling the built-in scheduler for external Celery/cron use
- Azure Blob managed identity setup
- SharePoint app registration steps
- Microsoft Entra ID app registration

---

## Support

- **Email:** inquiry@masridigital.com
- **Website:** [masridigital.com](https://masridigital.com)
- **Internal Issues:** Open a GitHub issue in this repo

---

*Built and maintained by [Masri Digital](https://masridigital.com)*
