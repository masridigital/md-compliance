# MD Compliance — Setup & Deployment Guide

This guide covers everything you need to deploy MD Compliance in a production environment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Variables](#environment-variables)
3. [Docker Deployment](#docker-deployment)
4. [Database Setup](#database-setup)
5. [Default Credentials](#default-credentials)
6. [Storage Integrations](#storage-integrations)
7. [Microsoft Entra ID](#microsoft-entra-id)
8. [LLM Configuration](#llm-configuration)
9. [Teams Notifications](#teams-notifications)
10. [Scheduler](#scheduler)
11. [SSL / Reverse Proxy](#ssl--reverse-proxy)
12. [Multi-Worker Deployment](#multi-worker-deployment)

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2+
- A PostgreSQL 14+ database (included in `docker-compose.yml`)
- (Optional) An SMTP server for email notifications
- (Optional) Azure subscription for Blob/SharePoint/Entra features

---

## Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

### Required

```env
SECRET_KEY=replace-with-a-long-random-string
POSTGRES_PASSWORD=replace-with-a-strong-password
```

> Generate a secret key: `python3 -c "import secrets; print(secrets.token_hex(32))"`

### Full Reference

#### App

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | Flask secret — used for session encryption and Fernet-encrypted settings |
| `APP_NAME` | `MD Compliance` | Display name shown in the UI and emails |
| `APP_PRIMARY_COLOR` | `#0066CC` | Brand hex color (overridable in Settings UI) |
| `SUPPORT_EMAIL` | `support@masridigital.com` | Support contact shown in the UI |
| `APP_ENV` | `production` | `development` or `production` |
| `PORT` | `8000` | HTTP port the app listens on |

#### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `postgres` | PostgreSQL host (use `postgres` inside Docker) |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `mdcompliance` | Database name |
| `POSTGRES_USER` | `mdcompliance` | Database user |
| `POSTGRES_PASSWORD` | *(required)* | Database password |

#### Email (SMTP)

| Variable | Default | Description |
|----------|---------|-------------|
| `MAIL_SERVER` | — | SMTP server hostname |
| `MAIL_PORT` | `587` | SMTP port |
| `MAIL_USERNAME` | — | SMTP login username |
| `MAIL_PASSWORD` | — | SMTP login password |
| `MAIL_USE_TLS` | `true` | Enable STARTTLS |

#### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_ENABLED` | `false` | Global kill switch for all LLM features |

LLM provider credentials (API keys, model names, token budgets) are configured in **Settings UI → LLM** and stored encrypted in the database.

#### Microsoft Entra ID

| Variable | Description |
|----------|-------------|
| `ENTRA_TENANT_ID` | Azure AD Directory (tenant) ID |
| `ENTRA_CLIENT_ID` | Application (client) ID |
| `ENTRA_CLIENT_SECRET` | Client secret value |

#### Notifications

| Variable | Description |
|----------|-------------|
| `TEAMS_WEBHOOK_URL` | Microsoft Teams incoming webhook URL |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `TWILIO_ACCOUNT_SID` | Twilio SID (for SMS) |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio sending phone number |

#### Scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `MASRI_SCHEDULER_ENABLED` | `true` | Enable the built-in background scheduler |

---

## Docker Deployment

### Start everything

```bash
docker-compose up -d
```

### Stop

```bash
docker-compose down
```

### View logs

```bash
docker-compose logs -f app
```

### Rebuild after code changes

```bash
docker-compose up -d --build
```

---

## Database Setup

On first launch, the app creates tables automatically. If you need to run migrations manually:

```bash
docker-compose exec app flask db upgrade
```

### Reset the database (⚠ deletes all data)

```bash
RESET_DB=yes docker-compose up -d
```

---

## Default Credentials

| Field | Value |
|-------|-------|
| Email | `admin@example.com` |
| Password | `admin1234567` |

**Change the password immediately** after first login via **Settings → Users**.

---

## Storage Integrations

Storage providers are configured in **Settings UI → Storage**. Only one provider is active at a time.

### Azure Blob Storage

1. Create a Storage Account in the [Azure Portal](https://portal.azure.com)
2. Under **Access control (IAM)**, assign the `Storage Blob Data Contributor` role to your app's managed identity (or create a connection string for key-based access)
3. In Settings UI → Storage: select **Azure Blob**, enter your Storage Account name and connection string

Per-tenant containers are created automatically on first use.

### SharePoint (Microsoft 365)

1. Register an Azure AD app at [portal.azure.com](https://portal.azure.com) → App registrations
2. Add API permissions: `Sites.ReadWrite.All`, `Files.ReadWrite.All`
3. Create a client secret
4. In Settings UI → Storage: select **SharePoint**, enter Tenant ID, Client ID, Client Secret, and Site URL

Auto-folder structure is created per tenant on first use.

### Amazon S3 (or S3-compatible)

In Settings UI → Storage: select **S3**, enter:
- Access Key ID
- Secret Access Key
- Bucket Name
- Region (or custom endpoint URL for S3-compatible stores)

### Egnyte

In Settings UI → Storage: select **Egnyte**, enter:
- Egnyte domain (e.g. `mycompany.egnyte.com`)
- API token

### Local Storage

Files are stored on the server filesystem. Path is configured by the `LOCAL_STORAGE_PATH` environment variable (default: `app/uploads/`). Not recommended for production multi-worker deployments.

---

## Microsoft Entra ID

The Entra ID integration uses Microsoft Graph API to pull user lists, MFA status, conditional access policies, and Intune device compliance into the compliance dashboard.

### App Registration Steps

1. Go to [portal.azure.com](https://portal.azure.com) → **Azure Active Directory → App registrations → New registration**
2. Name: `MD Compliance`
3. Supported account types: **Single tenant**
4. Click **Register**
5. Copy the **Application (client) ID** and **Directory (tenant) ID**
6. Go to **Certificates & secrets → New client secret** — copy the value immediately
7. Go to **API permissions → Add a permission → Microsoft Graph → Application permissions**
   - `User.Read.All`
   - `Policy.Read.All`
   - `Reports.Read.All`
   - `DeviceManagementManagedDevices.Read.All` *(optional, for Intune)*
8. Click **Grant admin consent**
9. Add the three values to your `.env`:

```env
ENTRA_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ENTRA_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ENTRA_CLIENT_SECRET=your-secret-value
```

---

## LLM Configuration

LLM features are configured entirely in **Settings UI → LLM** (no restart required).

### Supported Providers

| Provider | Models |
|----------|--------|
| **OpenAI** | GPT-4o, GPT-4, GPT-3.5-turbo |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3 Opus |
| **Azure OpenAI** | Your custom deployment names |
| **Ollama** | Llama 3, Mistral, any locally-hosted model |

### What LLM Powers

- Control assessment assistance
- Gap narrative generation
- Evidence interpretation
- Risk scoring
- WISP wizard content generation

Per-tenant token budgets can be set in the Settings UI to control costs.

---

## Teams Notifications

1. In Microsoft Teams, go to the channel you want alerts in
2. **More options → Connectors → Incoming Webhook → Configure**
3. Name it `MD Compliance`, copy the webhook URL
4. Paste it in **Settings UI → Notifications → Teams Webhook URL**

### Event Types

| Event | Default |
|-------|---------|
| Control due date (30d / 7d / 1d / on-due) | Enabled |
| Control marked overdue | Enabled |
| New finding added | Enabled |
| Framework assessment complete | Enabled |
| WISP document published | Optional |
| User access changes | Optional |

Each alert includes action buttons (View Control, Mark In Progress) that deep-link back into the platform.

---

## Scheduler

The built-in scheduler runs two background jobs using Python threading (zero external dependencies):

| Job | Frequency | What It Does |
|-----|-----------|-------------|
| Due date reminders | Every 1 hour | Checks all controls for upcoming/overdue due dates and fires notifications |
| Drift detection | Every 24 hours | Compares current control states to the last snapshot and flags unexpected changes |

### Disable for Multi-Worker Deployments

If you run multiple app workers (e.g. Gunicorn with multiple workers), disable the built-in scheduler to avoid duplicate jobs:

```env
MASRI_SCHEDULER_ENABLED=false
```

Then schedule the reminder check externally:

```bash
# Example cron (every hour)
0 * * * * curl -X POST https://your-domain/api/v1/notifications/check-reminders \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## SSL / Reverse Proxy

The app does not handle SSL directly. Use a reverse proxy in front of it.

### nginx example

```nginx
server {
    listen 443 ssl;
    server_name compliance.masridigital.com;

    ssl_certificate     /etc/letsencrypt/live/compliance.masridigital.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/compliance.masridigital.com/privkey.pem;

    location / {
        proxy_pass         http://localhost:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

---

## Multi-Worker Deployment

For higher availability, run multiple Gunicorn workers:

```dockerfile
# In docker-compose.yml, override the command:
command: gunicorn -w 4 -b 0.0.0.0:8000 flask_app:app
```

When using multiple workers:
- Set `MASRI_SCHEDULER_ENABLED=false` and use an external scheduler (see [Scheduler](#scheduler))
- Use a shared storage provider (Azure Blob, SharePoint, or S3) — not Local
- Use Redis for session storage if sticky sessions are not available

---

*Questions? Email support@masridigital.com or open a GitHub issue.*
