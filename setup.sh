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

# ── Detect public IP ──────────────────────────────────────────────────────────────
info "Detecting this server's public IP address..."
SERVER_IP=$(curl -s --max-time 6 https://api.ipify.org 2>/dev/null \
    || curl -s --max-time 6 https://ifconfig.me 2>/dev/null \
    || curl -s --max-time 6 https://checkip.amazonaws.com 2>/dev/null \
    || echo "")

if [ -z "$SERVER_IP" ]; then
    warn "Could not detect public IP automatically."
    warn "Find it manually with: curl https://api.ipify.org"
    SERVER_IP="<your-server-ip>"
else
    log "Server public IP: ${BOLD}${SERVER_IP}${RESET}"
fi

# ── Step 1: Domain ────────────────────────────────────────────
header "Step 1 of 4 — Domain & DNS"
echo "Log into your DNS provider and create an A record pointing"
echo "your domain to this server before continuing."
echo ""
echo -e "  ${BOLD}Record type:${RESET}  A"
echo -e "  ${BOLD}Host / Name:${RESET}  @ or subdomain  (e.g. compliance)"
echo -e "  ${BOLD}Value:${RESET}        ${BOLD}${CYAN}${SERVER_IP}${RESET}"
echo -e "  ${BOLD}TTL:${RESET}          300 seconds  (or lowest available)"
echo ""
echo "DNS changes typically take 1-10 minutes to propagate."
echo "This setup will verify the record before requesting your SSL certificate."
echo ""
echo "Enter the domain or subdomain you are setting up:"
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

# ── DNS verification ──────────────────────────────────────────────────────────
info "Verifying DNS for ${DOMAIN}..."
DOMAIN_IP=$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 \
    || dig +short "$DOMAIN" 2>/dev/null | grep -E '^[0-9]+\.' | tail -1 \
    || echo "")

if [ -z "$DOMAIN_IP" ]; then
    warn "${DOMAIN} does not resolve yet — DNS has not propagated."
    warn "Make sure you added the A record pointing to ${SERVER_IP}."
    prompt "Press Enter to check again, or Ctrl-C to exit and retry later:"
    read -r _
    DOMAIN_IP=$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || echo "")
    if [ -z "$DOMAIN_IP" ]; then
        warn "Still not resolving. Continuing anyway — SSL may fail if DNS is not ready."
    fi
elif [ "$DOMAIN_IP" = "$SERVER_IP" ]; then
    log "DNS verified — ${DOMAIN} → ${SERVER_IP}"
else
    warn "DNS mismatch detected!"
    warn "  ${DOMAIN} currently resolves to: ${DOMAIN_IP}"
    warn "  This server's IP is:             ${SERVER_IP}"
    warn "  Update your A record to ${SERVER_IP} and wait for propagation."
    prompt "Continue anyway? [y/N]"
    read -r DNS_OVERRIDE
    if [[ ! "$DNS_OVERRIDE" =~ ^[Yy]$ ]]; then
        info "Exiting. Fix your DNS A record, then re-run ./setup.sh"
        exit 0
    fi
fi


# ── Step 2: SSL ───────────────────────────────────────────────────────────────
header "Step 2 of 4 — SSL Certificate"
echo "MD Compliance can automatically obtain a free SSL certificate"
echo "from Let's Encrypt via Certbot."
echo ""
echo "  Two verification methods are available:"
echo ""
echo -e "  ${BOLD}1) HTTP (webroot)${RESET}  — Certbot places a file on port 80 for verification."
echo "     Requires port 80 to be open and reachable from the internet."
echo ""
echo -e "  ${BOLD}2) DNS (TXT record)${RESET} — Certbot gives you a TXT record to add to your DNS."
echo "     Works even if port 80 is blocked by a firewall."
echo "     You will be prompted to add the record, then press Enter to continue."
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
    echo ""
    prompt "Which verification method? [1=HTTP / 2=DNS] (default: 1):"
    read -r SSL_METHOD_CHOICE
    SSL_METHOD_CHOICE=${SSL_METHOD_CHOICE:-1}
    if [[ "$SSL_METHOD_CHOICE" == "2" ]]; then
        SSL_METHOD="dns"
        warn "DNS challenge selected. You will need to add a TXT record to your DNS."
    else
        SSL_METHOD="http"
        info "HTTP (webroot) challenge selected. Ensure port 80 is open."
    fi
else
    USE_SSL=false
    SSL_METHOD=""
    warn "Skipping SSL — the app will run on HTTP only. Not recommended for production."
fi

# ── Step 3: App credentials ───────────────────────────────────────────────────
header "Step 3 of 4 — App Credentials"

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

# ── Step 4: Generate files ────────────────────────────────────────────────────
header "Step 4 of 4 — Generating Configuration"

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

# ── Admin credentials ─────────────────────────────────────────────────────────
DEFAULT_EMAIL=${ADMIN_EMAIL}
DEFAULT_PASSWORD=${ADMIN_PASSWORD}

# ── Email ─────────────────────────────────────────────────────────────────────
MAIL_SERVER=
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_USE_TLS=true
SUPPORT_EMAIL=${CERTBOT_EMAIL:-support@masridigital.com}

# ── Scheduler ─────────────────────────────────────────────────────────────────
MASRI_SCHEDULER_ENABLED=true

# ─────────────────────────────────────────────────────────────────────────────
# All other settings are configured in the Settings UI after first login:
#   LLM provider & API keys  → Settings → LLM
#   Teams / Slack webhooks   → Settings → Notifications
#   Storage (Azure/S3/etc.)  → Settings → Storage
#   SSO / OIDC               → Settings → SSO
#   Branding & colors        → Settings → Branding
#   Microsoft Entra ID       → Settings → Entra ID
# ─────────────────────────────────────────────────────────────────────────────
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
    info "DNS already verified earlier in setup."
fi

if [ "$USE_SSL" = true ]; then
    mkdir -p nginx/ssl/letsencrypt nginx/certbot-webroot

    if [ "$SSL_METHOD" = "dns" ]; then
        # ── DNS-01 manual challenge ──────────────────────────────────────────
        echo ""
        warn "DNS challenge: Certbot will display a TXT record you must add to your DNS."
        warn "Do NOT press Enter until you have added the record and it has propagated."
        echo ""
        info "Running Certbot (DNS-01 / manual)..."
        docker run -it --rm \
            -v "$(pwd)/nginx/ssl/letsencrypt:/etc/letsencrypt" \
            certbot/certbot certonly \
                --manual \
                --preferred-challenges dns \
                --email "$CERTBOT_EMAIL" \
                --agree-tos \
                --no-eff-email \
                -d "$DOMAIN"

        CERTBOT_EXIT=$?
    else
        # ── HTTP-01 webroot challenge ────────────────────────────────────────
        info "Starting nginx (port 80 needed for ACME challenge)..."
        $COMPOSE up -d nginx 2>/dev/null || true

        info "Running Certbot (HTTP-01 / webroot)..."
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

        CERTBOT_EXIT=$?
    fi

    if [ "$CERTBOT_EXIT" -eq 0 ]; then
        log "SSL certificate obtained for ${DOMAIN}"
    else
        error "Certbot failed."
        if [ "$SSL_METHOD" = "http" ]; then
            error "For HTTP challenge, check that:"
            error "  1. Port 80 is open and reachable from the internet"
            error "  2. ${DOMAIN} DNS points to this server (${SERVER_IP})"
            error "  3. No other service is using port 80"
            error ""
            error "If port 80 is blocked by your firewall/host, re-run setup.sh"
            error "and choose option 2 (DNS challenge) instead."
        else
            error "For DNS challenge, check that:"
            error "  1. You added the _acme-challenge TXT record to your DNS"
            error "  2. The record propagated before pressing Enter"
        fi
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
echo -e "  ${BOLD}Login:${RESET}    ${ADMIN_EMAIL}  /  (your chosen password)"
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
