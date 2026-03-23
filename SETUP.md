# MD Compliance — Setup & Deployment Guide

This guide covers everything you need to deploy MD Compliance in a production environment.

---

## Table of Contents

1. [Quick Setup (Recommended)](#quick-setup-recommended)
2. [Prerequisites](#prerequisites)
3. [Environment Variables](#environment-variables)
4. [Docker Deployment](#docker-deployment)
5. [Database Setup](#database-setup)
6. [Default Credentials](#default-credentials)
7. [Updating the App](#updating-the-app)
8. [Database Backups](#database-backups)
9. [Storage Integrations](#storage-integrations)
10. [Microsoft Entra ID](#microsoft-entra-id)
11. [LLM Configuration](#llm-configuration)
12. [Teams Notifications](#teams-notifications)
13. [Scheduler](#scheduler)
14. [SSL Certificate Details](#ssl-certificate-details)
15. [Multi-Worker Deployment](#multi-worker-deployment)
16. [Troubleshooting](#troubleshooting)

---

## Quick Setup (Recommended)

The fastest way to get MD Compliance running on your server is the interactive setup script. It will ask for your domain name, obtain a free SSL certificate via Let's Encrypt, generate your `.env` file, configure nginx, and start the app — all in one step.

### Prerequisites

- A Linux server (Ubuntu 22.04+ recommended) with Docker and Docker Compose installed
- A domain or subdomain pointed at your server's IP address (e.g. `compliance.masridigital.com`)
- Port 80 and 443 open in your firewall
- (Optional) An SMTP server for email notifications
- (Optional) Azure subscription for Blob/SharePoint/Entra features

### Install Docker on Ubuntu

```bash
# Install Docker Engine + Compose plugin in one step
curl -fsSL https://get.docker.com | sh

# Add your user to the docker group (no sudo needed going forward)
sudo usermod -aG docker $USER

# Apply group membership without logging out
newgrp docker

# Verify both are installed
docker --version
docker compose version
```

> Docker Compose v2 (`docker compose`) is required. The setup script detects it automatically. If you only have the older `docker-compose` (v1) binary, install the Compose plugin: `sudo apt-get install docker-compose-plugin`

### Open firewall ports (Ubuntu UFW)

```bash
sudo ufw allow 80
sudo ufw allow 443
sudo ufw reload
```

### Run the setup wizard

```bash
git clone https://github.com/masridigital/md-compliance.git
cd md-compliance
chmod +x setup.sh
./setup.sh
```

The wizard will ask you:
1. **Domain name** — e.g. `compliance.masridigital.com`
2. **SSL** — whether to obtain a free Let's Encrypt certificate automatically
3. **Email** — for SSL renewal notices
4. **Admin credentials** — email address and password for the first login (written to `.env` and used on first start)

After it completes, your app is running at `https://your-domain.com`.

> **Everything else** — LLM keys, Teams webhooks, storage providers, SSO, branding, Entra ID — is configured from the **Settings UI** inside the app. No editing config files required.

### What setup.sh creates

| File / Directory | Purpose |
|------------------|---------|
| `.env` | All app secrets and configuration |
| `nginx/conf.d/mdcompliance.conf` | nginx site config for your domain |
| `docker-compose.override.yml` | Injects DOMAIN into the app container |
| `nginx/ssl/letsencrypt/` | SSL certificates (managed by certbot) |

### Re-running setup

If you need to change your domain or regenerate config, just run `./setup.sh` again. Existing data is never touched.

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

On first launch inside Docker, the app initialises the database automatically via `run.sh`:

1. Waits for PostgreSQL to be ready
2. Detects whether the database is empty or already has tables
3. **Empty database:** runs `python manage.py init_db` — creates all tables and seeds the admin user + default roles
4. **Existing database:** runs `flask db upgrade` — applies any new migration files only, never touches existing data
5. Starts Gunicorn

### Manual database initialisation (local / non-Docker)

```bash
# Create all tables and seed defaults (fresh install only)
python manage.py init_db

# Apply new migrations on an existing database
flask db upgrade
```

### Reset the database (⚠ deletes all data)

```bash
RESET_DB=yes docker-compose up -d
```

---

## Default Credentials

The admin account is created using the email and password you enter in **Step 3** of `./setup.sh`. There are no hardcoded credentials.

If you skipped the setup wizard and started the app directly without setting `DEFAULT_EMAIL` / `DEFAULT_PASSWORD` in your `.env`, the fallback credentials are:

| Field | Value |
|-------|-------|
| Email | `admin@example.com` |
| Password | `admin1234567` |

**Change the password immediately** after first login via **Settings → Users**.

---

## Updating the App

Pulling new code and rebuilding **will never touch your database**. All your tenants, users, controls, WISP documents, and settings are safe.

### Standard update procedure

```bash
# 1. Pull the latest code
git pull origin main

# 2. (Recommended) Back up before updating
./scripts/db-backup.sh

# 3. Rebuild and restart
docker-compose up -d --build
```

That's it. On startup the app will:
- Detect that your database already exists
- Run `flask db upgrade` to apply any new schema changes (new columns or tables only — never drops or modifies existing data)
- Start the server

### How data is protected

| Action | Effect on data |
|--------|---------------|
| `git pull` | No effect — code only |
| `docker-compose up -d --build` | No effect — DB is on a named volume |
| `docker-compose down` | No effect — named volume persists |
| `docker-compose restart` | No effect |
| `docker-compose down -v` | ⚠ **Deletes volume** — intentional wipe |
| `RESET_DB=yes docker-compose up` | ⚠ **Wipes database** — requires explicit env var |

The only way to lose data is to explicitly run `docker-compose down -v` or set `RESET_DB=yes`.

### Adding a new migration (for developers)

When you add new model columns or tables:

```bash
# Auto-generate a migration from model changes
docker-compose exec app flask db migrate -m "describe what changed"

# Review the generated file in migrations/versions/
# Then apply it
docker-compose exec app flask db upgrade
```

Commit the migration file to git — it will be applied automatically on the next `docker-compose up --build`.

---

## Database Backups

### Create a backup

```bash
./scripts/db-backup.sh
# Saves to ./backups/mdcompliance_YYYY-MM-DD_HHMMSS.sql.gz
```

Backup to a specific directory:
```bash
./scripts/db-backup.sh /path/to/backups
```

### Restore a backup

```bash
./scripts/db-restore.sh backups/mdcompliance_2026-03-17_120000.sql.gz
```

The restore script will ask for confirmation before overwriting.

### Automated daily backups (optional)

Add to your server's crontab:
```bash
# Daily backup at 2am
0 2 * * * cd /path/to/md-compliance && ./scripts/db-backup.sh >> /var/log/mdcompliance-backup.log 2>&1
```

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

## SSL Certificate Details

SSL is handled automatically when you run `./setup.sh` — you do not need to configure nginx or Certbot manually.

### How it works

1. `setup.sh` generates an nginx config for your domain at `nginx/conf.d/mdcompliance.conf`
2. It starts nginx and runs Certbot in a temporary container to complete the ACME HTTP-01 challenge
3. Certificates are saved to `nginx/ssl/letsencrypt/`
4. A persistent `certbot` container checks for renewal every 12 hours automatically

### Manual renewal

```bash
./scripts/renew-ssl.sh
```

### Check certificate expiry

```bash
docker-compose exec certbot certbot certificates
```

### DNS requirements

Before running `setup.sh`, make sure your domain's DNS A record points to your server's IP. Let's Encrypt will fail if DNS hasn't propagated. You can check with:

```bash
dig +short your-domain.com
curl https://api.ipify.org   # your server's public IP
```

Both should return the same IP address.

### Firewall requirements

| Port | Required for |
|------|--------------|
| 80 | Let's Encrypt ACME challenge + HTTP redirect to HTTPS |
| 443 | HTTPS traffic |

On Ubuntu with UFW:
```bash
ufw allow 80
ufw allow 443
ufw reload
```

On AWS/GCP/Azure: open these ports in your security group / firewall rules.

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

## Troubleshooting

### App container exits immediately on first run

Check the logs:

```bash
docker-compose logs app
```

Common causes and fixes:

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'flask_script'` | Stale image with old code | `docker-compose build --no-cache && docker-compose up -d` |
| `SECRET_KEY must be set` | No `.env` file | Run `./setup.sh` or copy `.env.example` to `.env` and set `SECRET_KEY` |
| `could not connect to server` | Postgres not ready | Wait 10–15 seconds and restart: `docker-compose restart app` |
| `role "mdcompliance" does not exist` | Postgres env vars not passed | Ensure `.env` has `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| `permission denied` on `run.sh` | Script not executable | `chmod +x run.sh` then rebuild |

### Setup wizard hangs at "Waiting for the app to be ready"

The health check polls `http://localhost:5000` up to 12 times (60 seconds). If it never responds:

```bash
# Check what the app container is doing
docker-compose logs app

# Common fix — the DB took too long to start; just restart the app
docker-compose restart app
```

### `docker compose` not found (Ubuntu)

The setup script supports both `docker compose` (v2, plugin) and `docker-compose` (v1, standalone). Install the plugin:

```bash
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
docker compose version   # should print v2.x
```

### SSL certificate fails

Certbot requires that:
- Port 80 is open and reachable from the internet
- Your domain's DNS A record points to the server's public IP

Check DNS propagation:
```bash
dig +short your-domain.com    # should match your server IP
curl https://api.ipify.org    # your server's public IP
```

If DNS isn't ready, re-run the wizard after propagation:
```bash
./setup.sh
```

### Database connection refused after update

If you see `could not connect to server: Connection refused` after a `git pull`:

```bash
# Postgres might still be starting — give it a moment, then restart the app
docker-compose restart app
docker-compose logs -f app
```

---

*Questions? Email support@masridigital.com or open a GitHub issue.*
