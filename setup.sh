#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Interactive Setup Script
#
# Run this ONCE on a fresh server to configure your domain, SSL certificate,
# and environment before starting the app for the first time.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
RESET="\033[0m"

log()     { echo -e "${GREEN}[✓]${RESET} $*"; }
info()    { echo -e "${CYAN}[→]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}$*${RESET}\n"; }
prompt()  { echo -e "${BOLD}$*${RESET}"; }

# ── Dependency check ──────────────────────────────────────────────────────────
check_deps() {
    local missing=()
    for cmd in docker openssl; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done

    # docker compose (v2) or docker-compose (v1)
    if ! docker compose version &>/dev/null 2>&1 && ! command -v docker-compose &>/dev/null; then
        missing+=("docker-compose")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        error "Missing required tools: ${missing[*]}"
        info "Install Docker: https://docs.docker.com/engine/install/"
        exit 1
    fi

    # Detect compose command
    if docker compose version &>/dev/null 2>&1; then
        COMPOSE="docker compose"
    else
        COMPOSE="docker-compose"
    fi
}

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║       MD Compliance — Setup Wizard       ║"
echo "  ║         Masri Digital · masridigital.com ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${RESET}"
echo "This script will configure your domain, SSL certificate,"
echo "and environment file, then start MD Compliance."
echo ""

check_deps

# ── Step 1: Domain ────────────────────────────────────────────────────────────
header "Step 1 of 5 — Domain"
echo "Enter the domain or subdomain where MD Compliance will run."
echo "Examples:  compliance.masridigital.com   mdcompliance.com"
echo ""
while true; do
    prompt "Domain name:"
    read -r DOMAIN
    DOMAIN=$(echo "$DOMAIN" | tr '[:upper:]' '[:lower:]' | sed 's|https\?://||g' | sed 's|/||g')
    if [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$ ]]; then
        log "Domain set to: $DOMAIN"
        break
    else
        error "That doesn't look like a valid domain. Please try again."
    fi
done

# ── Step 2: SSL ───────────────────────────────────────────────────────────────
header "Step 2 of 5 — SSL Certificate"
echo "MD Compliance can automatically obtain a free SSL certificate"
echo "from Let's Encrypt via Certbot."
echo ""
echo "  Requirements:"
echo "   • Port 80 and 443 must be open on this server"
echo "   • The domain DNS must already point to this server's IP"
echo ""
prompt "Set up SSL automatically with Let's Encrypt? [Y/n]"
read -r SSL_CHOICE
SSL_CHOICE=${SSL_CHOICE:-Y}

if [[ "$SSL_CHOICE" =~ ^[Yy]$ ]]; then
    USE_SSL=true
    while true; do
        prompt "Email address for SSL certificate renewal notices:"
        read -r CERTBOT_EMAIL
        if [[ "$CERTBOT_EMAIL" =~ ^[^@]+@[^@]+\.[^@]+$ ]]; then
            log "Certbot email: $CERTBOT_EMAIL"
            break
        else
            error "Please enter a valid email address."
        fi
    done
else
    USE_SSL=false
    warn "Skipping SSL — the app will run on HTTP only. Not recommended for production."
fi

# ── Step 3: App credentials ───────────────────────────────────────────────────
header "Step 3 of 5 — App Credentials"

# Secret key
SECRET_KEY=$(openssl rand -hex 32)
log "Generated SECRET_KEY (random 256-bit)"

# Database password
DB_PASSWORD=$(openssl rand -hex 16)
log "Generated database password (random)"

echo ""
prompt "Admin email address (used to log in):"
read -r ADMIN_EMAIL
ADMIN_EMAIL=${ADMIN_EMAIL:-admin@masridigital.com}

prompt "Admin password (leave blank to use default 'admin1234567'):"
read -rs ADMIN_PASSWORD
echo ""
ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin1234567}

# ── Step 4: Optional integrations ────────────────────────────────────────────
header "Step 4 of 5 — Optional Integrations"
echo "Press Enter to skip any integration — you can configure these"
echo "later from the Settings UI inside the app."
echo ""

prompt "Teams webhook URL (for alerts and reminders) [optional]:"
read -r TEAMS_WEBHOOK

prompt "LLM API key — OpenAI or Anthropic [optional]:"
read -rs LLM_KEY
echo ""

if [ -n "$LLM_KEY" ]; then
    echo ""
    echo "LLM Provider:"
    echo "  1) OpenAI"
    echo "  2) Anthropic"
    echo "  3) Azure OpenAI"
    prompt "Choice [1]:"
    read -r LLM_PROVIDER_CHOICE
    case "$LLM_PROVIDER_CHOICE" in
        2) LLM_PROVIDER="anthropic" ;;
        3) LLM_PROVIDER="azure_openai" ;;
        *) LLM_PROVIDER="openai" ;;
    esac
    LLM_ENABLED="true"
else
    LLM_PROVIDER="openai"
    LLM_ENABLED="false"
fi

# ── Step 5: Generate files ────────────────────────────────────────────────────
header "Step 5 of 5 — Generating Configuration"

# ── .env ─────────────────────────────────────────────────────────────────────
info "Writing .env..."
cat > .env <<EOF
# ── MD Compliance Environment ─────────────────────────────────────────────────
# Generated by setup.sh on $(date -u "+%Y-%m-%d %H:%M UTC")
# Edit this file to update any setting. Re-run: docker-compose up -d --build

# ── App ───────────────────────────────────────────────────────────────────────
SECRET_KEY=${SECRET_KEY}
APP_NAME=MD Compliance
APP_ENV=production
DOMAIN=${DOMAIN}
PORT=5000

# ── Database ──────────────────────────────────────────────────────────────────
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=mdcompliance
POSTGRES_USER=mdcompliance
POSTGRES_PASSWORD=${DB_PASSWORD}

# ── Email ─────────────────────────────────────────────────────────────────────
MAIL_SERVER=
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_USE_TLS=true
SUPPORT_EMAIL=${CERTBOT_EMAIL:-support@masridigital.com}

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_ENABLED=${LLM_ENABLED}
LLM_NAME=${LLM_PROVIDER}
LLM_TOKEN=${LLM_KEY}

# ── Notifications ─────────────────────────────────────────────────────────────
TEAMS_WEBHOOK_URL=${TEAMS_WEBHOOK}
SLACK_WEBHOOK_URL=

# ── Microsoft Entra ID ────────────────────────────────────────────────────────
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=

# ── Branding ──────────────────────────────────────────────────────────────────
APP_PRIMARY_COLOR=#0066CC

# ── Scheduler ─────────────────────────────────────────────────────────────────
MASRI_SCHEDULER_ENABLED=true
EOF
log ".env created"

# ── nginx config ─────────────────────────────────────────────────────────────
mkdir -p nginx/conf.d nginx/ssl

if [ "$USE_SSL" = true ]; then
    info "Writing nginx config (HTTPS with Let's Encrypt)..."
    cat > nginx/conf.d/mdcompliance.conf <<EOF
# MD Compliance — nginx configuration
# Domain: ${DOMAIN}
# Generated by setup.sh

# Redirect HTTP → HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

# HTTPS
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache   shared:SSL:10m;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Security headers
    add_header X-Frame-Options           SAMEORIGIN always;
    add_header X-Content-Type-Options    nosniff    always;
    add_header X-XSS-Protection          "1; mode=block" always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;

    client_max_body_size 50M;

    location / {
        proxy_pass         http://app:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
    }
}
EOF
else
    info "Writing nginx config (HTTP only)..."
    cat > nginx/conf.d/mdcompliance.conf <<EOF
# MD Compliance — nginx configuration (HTTP only)
# Domain: ${DOMAIN}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 50M;

    location / {
        proxy_pass         http://app:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
    }
}
EOF
fi
log "nginx config written → nginx/conf.d/mdcompliance.conf"

# ── docker-compose override ───────────────────────────────────────────────────
info "Writing docker-compose.override.yml..."
cat > docker-compose.override.yml <<EOF
# Auto-generated by setup.sh — do not edit manually
# Re-run setup.sh to regenerate
services:
  app:
    environment:
      - DOMAIN=${DOMAIN}
EOF
log "docker-compose.override.yml written"

# ── SSL certificate via Certbot ───────────────────────────────────────────────
if [ "$USE_SSL" = true ]; then
    echo ""
    header "Obtaining SSL Certificate"
    info "Checking that ${DOMAIN} resolves to this server..."

    SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "unknown")
    DOMAIN_IP=$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || dig +short "$DOMAIN" 2>/dev/null | tail -1 || echo "unresolved")

    echo "  Server IP : ${SERVER_IP}"
    echo "  Domain IP : ${DOMAIN_IP}"
    echo ""

    if [ "$SERVER_IP" != "$DOMAIN_IP" ] && [ "$DOMAIN_IP" != "unresolved" ]; then
        warn "DNS mismatch detected!"
        warn "  ${DOMAIN} resolves to ${DOMAIN_IP}"
        warn "  This server's IP is ${SERVER_IP}"
        echo ""
        warn "Let's Encrypt will fail if DNS hasn't propagated yet."
        prompt "Continue anyway? [y/N]"
        read -r DNS_CONTINUE
        if [[ ! "$DNS_CONTINUE" =~ ^[Yy]$ ]]; then
            warn "Skipping Certbot. Fix DNS, then run: ./scripts/renew-ssl.sh"
            USE_SSL=false
        fi
    fi
fi

if [ "$USE_SSL" = true ]; then
    info "Starting nginx (port 80 needed for ACME challenge)..."
    $COMPOSE up -d nginx 2>/dev/null || true

    info "Running Certbot..."
    docker run --rm \
        -v "$(pwd)/nginx/ssl/letsencrypt:/etc/letsencrypt" \
        -v "$(pwd)/nginx/certbot-webroot:/var/www/certbot" \
        certbot/certbot certonly \
            --webroot \
            --webroot-path=/var/www/certbot \
            --email "$CERTBOT_EMAIL" \
            --agree-tos \
            --no-eff-email \
            -d "$DOMAIN" \
            --non-interactive

    if [ $? -eq 0 ]; then
        log "SSL certificate obtained for ${DOMAIN}"
    else
        error "Certbot failed. Check that:"
        error "  1. Port 80 is open and reachable from the internet"
        error "  2. ${DOMAIN} DNS points to this server"
        error "  3. No other service is using port 80"
        echo ""
        warn "To retry SSL setup later, run: ./scripts/renew-ssl.sh"
        warn "Falling back to HTTP for now..."
        USE_SSL=false
        # Rewrite nginx config to HTTP-only
        cat > nginx/conf.d/mdcompliance.conf <<NGINXEOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    client_max_body_size 50M;
    location / {
        proxy_pass         http://app:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF
    fi
fi

# ── Start the app ─────────────────────────────────────────────────────────────
header "Starting MD Compliance"
info "Building and starting all services..."
$COMPOSE up -d --build

info "Waiting for the app to be ready..."
sleep 8

# Health check
APP_UP=false
for i in {1..12}; do
    if curl -sf "http://localhost:5000" &>/dev/null; then
        APP_UP=true
        break
    fi
    sleep 5
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║           MD Compliance is running!              ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${RESET}"
echo ""

if [ "$USE_SSL" = true ]; then
    echo -e "  ${BOLD}URL:${RESET}      https://${DOMAIN}"
else
    echo -e "  ${BOLD}URL:${RESET}      http://${DOMAIN}"
fi

echo ""
echo -e "  ${BOLD}Login:${RESET}    admin@example.com  /  admin1234567"
echo -e "  ${BOLD}Note:${RESET}     Change the password immediately after first login"
echo ""
echo -e "  ${BOLD}Settings stored in:${RESET}  .env"
echo -e "  ${BOLD}nginx config:${RESET}        nginx/conf.d/mdcompliance.conf"
echo ""

if [ "$USE_SSL" = true ]; then
    echo -e "  ${BOLD}SSL auto-renewal:${RESET}"
    echo "   Certificates renew automatically via the certbot service."
    echo "   To manually force renewal: ./scripts/renew-ssl.sh"
    echo ""
fi

echo -e "  ${BOLD}Useful commands:${RESET}"
echo "   View logs:          docker-compose logs -f app"
echo "   Stop:               docker-compose down"
echo "   Update app:         git pull && ./scripts/update.sh"
echo "   Backup database:    ./scripts/db-backup.sh"
echo ""
