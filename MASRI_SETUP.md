# Masri Digital Compliance Platform — Setup Guide

## Overview

Masri Digital extends the Gapps compliance platform with advanced features:
- WISP (Written Information Security Program) document wizard and export
- Multi-provider LLM integration (OpenAI, Anthropic, Azure OpenAI, Ollama)
- MCP (Model Context Protocol) API server
- Microsoft Entra ID (Azure AD) integration
- Multi-channel notifications (Teams, Email, Slack, SMS)
- Background scheduler for due-date reminders and drift detection
- PWA support with branded icons

## Quick Start

### 1. Environment Setup

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 2. Docker Deployment

```bash
docker-compose up -d
```

The app runs on port 8000 by default.

### 3. Database Migration

```bash
docker-compose exec app flask db upgrade
```

### 4. Default Login

- Email: `admin@example.com`
- Password: `admin1234567`

Change these immediately in production via the `.env` file.

## Configuration Reference

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change_secret_key` | Flask secret key — **must change in production** |
| `APP_NAME` | `Masri Digital` | Application display name |
| `APP_PRIMARY_COLOR` | `#0066CC` | Brand color (hex) |
| `SUPPORT_EMAIL` | `support@masridigital.com` | Support contact email |

### LLM Configuration

LLM features are configured in the admin Settings panel (stored in the database).
The `LLM_ENABLED` environment variable acts as a global kill switch.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_ENABLED` | `false` | Enable LLM features globally |
| `LLM_NAME` | _(empty)_ | Provider name for legacy config |
| `LLM_TOKEN` | _(empty)_ | API key for legacy config |

Supported providers (configured via Settings UI):
- **OpenAI** — GPT-4o, GPT-4, GPT-3.5
- **Anthropic** — Claude Sonnet, Claude Opus
- **Azure OpenAI** — Custom deployments
- **Ollama** — Local models (Llama, Mistral, etc.)

### Microsoft Entra ID

Register an Azure AD app at [portal.azure.com](https://portal.azure.com):
1. App registrations > New registration
2. Add API permissions: `User.Read.All`, `Policy.Read.All`, `Reports.Read.All`
3. Create a client secret
4. Set the values below

| Variable | Description |
|----------|-------------|
| `ENTRA_TENANT_ID` | Azure AD Directory (tenant) ID |
| `ENTRA_CLIENT_ID` | Application (client) ID |
| `ENTRA_CLIENT_SECRET` | Client secret value |

### Notifications

| Variable | Description |
|----------|-------------|
| `TEAMS_WEBHOOK_URL` | Microsoft Teams incoming webhook URL |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `TWILIO_ACCOUNT_SID` | Twilio account SID (for SMS) |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio sending phone number |

### Scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `MASRI_SCHEDULER_ENABLED` | `true` | Enable background scheduler |

The scheduler runs:
- **Due-date reminders** — every 1 hour
- **Drift detection** — every 24 hours

For multi-worker deployments, disable the built-in scheduler and use an
external scheduler (Celery Beat, cron, etc.).

## API Endpoints

### WISP API (`/api/v1/wisp`)
- `POST /assist` — LLM content generation for wizard steps
- `POST /generate` — Generate final WISP document
- `POST /<id>/export/pdf` — Export branded PDF
- `POST /<id>/export/docx` — Export branded DOCX
- `POST /<id>/sign` — Digital signature capture
- `GET /<id>/versions` — Version history
- `POST /<id>/llm-generate` — LLM-generate section text

### LLM API (`/api/v1/llm`)
- `POST /control-assist` — Control assessment
- `POST /gap-narrative` — Gap analysis narrative
- `POST /risk-score` — Risk scoring
- `POST /interpret-evidence` — Evidence interpretation
- `GET /usage` — Token usage stats

### Notifications API (`/api/v1/notifications`)
- `POST /test-teams` — Test Teams notification
- `POST /test-email` — Test email notification
- `POST /send` — Send notification (any channel)
- `GET /logs` — Notification logs
- `POST /check-reminders` — Trigger reminder check

### Entra ID API (`/api/v1/entra`)
- `POST /test` — Test Graph API connection
- `GET /users` — List directory users
- `GET /mfa-status` — MFA registration status
- `POST /assess` — Compliance posture assessment

### MCP API (`/mcp/v1`)
- `GET /tools` — Tool discovery
- `POST /tools/<name>` — Tool execution

### Settings API (`/api/v1/settings`)
- Notification, LLM, storage, SSO, and branding configuration

## Architecture

```
app/masri/
├── config_additions.py    # Default config values
├── context_processors.py  # Jinja2 template injection
├── entra_integration.py   # Microsoft Entra ID client
├── entra_routes.py        # Entra ID API endpoints
├── generate_icons.py      # PWA icon generator
├── llm_routes.py          # LLM API endpoints
├── llm_service.py         # Multi-provider LLM facade
├── mcp_server.py          # MCP protocol server
├── new_models.py          # SQLAlchemy models
├── notification_engine.py # Multi-channel dispatcher
├── notification_routes.py # Notification API endpoints
├── scheduler.py           # Background task scheduler
├── settings_routes.py     # Settings API endpoints
├── settings_service.py    # Settings business logic
├── wisp_export.py         # PDF/DOCX/HTML exporter
└── wisp_routes.py         # WISP API endpoints
```

## Dependencies

Add to `requirements.txt` as needed:
```
reportlab        # PDF generation
python-docx      # DOCX generation
msal             # Microsoft Entra ID auth
Pillow           # Icon generation (optional)
```
