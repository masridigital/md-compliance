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
DOMAIN_IP=$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1)
if [ -z "$DOMAIN_IP" ]; then
    DOMAIN_IP=$(dig +short "$DOMAIN" 2>/dev/null | grep -E '^[0-9]+\.' | tail -1 || true)
fi

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
prompt "Set up SSL automatically with Let's Encrypt? [Y/n]"
read -r SSL_CHOICE
SSL_CHOICE=${SSL_CHOICE:-Y}

if [[ "$SSL_CHOICE" =~ ^[Yy]$ ]]; then
    USE_SSL=true

    echo ""
    echo "  Two verification methods are available:"
    echo ""
    echo -e "  ${BOLD}1) HTTP (webroot)${RESET}"
    echo "     Certbot places a small file on port 80 for Let's Encrypt to fetch."
    echo "     Requires port 80 to be open and reachable from the internet."
    echo ""
    echo -e "  ${BOLD}2) DNS TXT record${RESET}"
    echo "     You add a TXT record to your DNS to prove domain ownership."
    echo "     Works even if port 80 is blocked by a firewall or proxy."
    echo "     The script will display the exact record to add and pause"
    echo "     until you confirm it has been added before verifying."
    echo ""
    prompt "Which verification method? [1=HTTP / 2=DNS TXT] (default: 1):"
    read -r SSL_METHOD_CHOICE
    SSL_METHOD_CHOICE=${SSL_METHOD_CHOICE:-1}
    if [[ "$SSL_METHOD_CHOICE" == "2" ]]; then
        SSL_METHOD="dns"
        log "DNS TXT record challenge selected."
    else
        SSL_METHOD="http"
        log "HTTP (webroot) challenge selected. Ensure port 80 is open."
    fi

    echo ""
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
    SSL_METHOD=""
    warn "Skipping SSL — the app will run on HTTP only. Not recommended for production."
fi

# ── Step 3: Generate secrets ─────────────────────────────────────────────────
header "Step 3 of 3 — Generating Configuration"

# Secret key — reuse from existing .env if present, so re-runs are safe
if [ -f .env ]; then
    EXISTING_SECRET=$(grep -E '^SECRET_KEY=' .env 2>/dev/null | cut -d= -f2-)
    EXISTING_DB_PW=$(grep -E '^POSTGRES_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)
fi

if [ -n "$EXISTING_SECRET" ]; then
    SECRET_KEY="$EXISTING_SECRET"
    log "Reusing existing SECRET_KEY from .env"
else
    SECRET_KEY=$(openssl rand -hex 32)
    log "Generated SECRET_KEY (random 256-bit)"
fi

# Database password — MUST reuse on re-runs; Postgres stores the password on
# first init and a new random value would cause auth failures.
if [ -n "$EXISTING_DB_PW" ]; then
    DB_PASSWORD="$EXISTING_DB_PW"
    log "Reusing existing database password from .env"
else
    DB_PASSWORD=$(openssl rand -hex 16)
    log "Generated database password (random)"
fi

info "Admin account will be created in the web UI on first visit."

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

# ── Admin ─────────────────────────────────────────────────────────────────────
# Admin account is created via the web UI on first visit (no .env credentials).

# ── SSL / Certbot ─────────────────────────────────────────────────────────────
CERTBOT_EMAIL=${CERTBOT_EMAIL:-}

# ── Email ─────────────────────────────────────────────────────────────────────
MAIL_SERVER=
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_USE_TLS=true
SUPPORT_EMAIL=${CERTBOT_EMAIL:-inquiry@masridigital.com}

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

    # Branded error page during app startup/restart
    error_page 502 503 504 /502.html;
    location = /502.html {
        root /usr/share/nginx/error-pages;
        internal;
    }

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

    error_page 502 503 504 /502.html;
    location = /502.html {
        root /usr/share/nginx/error-pages;
        internal;
    }

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

    mkdir -p nginx/ssl/letsencrypt nginx/certbot-webroot

    CERTBOT_EXIT=0

    if [ "$SSL_METHOD" = "dns" ]; then
        # ── DNS-01 challenge via auth hook ───────────────────────────────────
        # Write a hook script that certbot will call with CERTBOT_DOMAIN and
        # CERTBOT_VALIDATION set.  The hook displays the TXT record details and
        # waits for the operator to add the record before certbot verifies it.
        mkdir -p nginx/certbot-hooks
        cat > nginx/certbot-hooks/dns-auth-hook.sh <<'DNSAUTHEOF'
#!/bin/sh
printf '\n'
printf '══════════════════════════════════════════════════════════════════════\n'
printf '  ACTION REQUIRED — ADD THIS DNS TXT RECORD TO YOUR DNS PROVIDER\n'
printf '══════════════════════════════════════════════════════════════════════\n'
printf '\n'
printf '  Record Type:  TXT\n'
printf '  Host / Name:  _acme-challenge.%s\n' "$CERTBOT_DOMAIN"
printf '  Value:        %s\n' "$CERTBOT_VALIDATION"
printf '  TTL:          60  (or the lowest value your provider allows)\n'
printf '\n'
printf '══════════════════════════════════════════════════════════════════════\n'
printf '\n'
printf 'Steps:\n'
printf '  1. Log in to your DNS provider\n'
printf '  2. Create a TXT record exactly as shown above\n'
printf '  3. Wait 1-3 minutes for the record to propagate\n'
printf '  4. Press Enter here — certbot will then verify and issue your cert\n'
printf '\n'
printf 'Waiting... Press Enter once the TXT record has been added: '
read -r _
DNSAUTHEOF
        chmod +x nginx/certbot-hooks/dns-auth-hook.sh

        echo ""
        info "Running Certbot (DNS-01 / TXT record)..."
        echo ""
        TTY_FLAG=$([ -t 0 ] && printf '%s' '-it' || printf '%s' '-i')
        docker run "$TTY_FLAG" --rm \
            -v "$(pwd)/nginx/ssl/letsencrypt:/etc/letsencrypt" \
            -v "$(pwd)/nginx/certbot-hooks:/certbot-hooks" \
            certbot/certbot certonly \
                --manual \
                --preferred-challenges dns \
                --manual-auth-hook /certbot-hooks/dns-auth-hook.sh \
                --manual-public-ip-logging-ok \
                --email "$CERTBOT_EMAIL" \
                --agree-tos \
                --no-eff-email \
                -d "$DOMAIN" \
            || CERTBOT_EXIT=$?
    else
        # ── HTTP-01 webroot challenge ────────────────────────────────────────
        # Write a temporary HTTP-only bootstrap nginx config (no SSL references)
        info "Writing temporary bootstrap nginx config for ACME challenge..."
        cat > nginx/conf.d/mdcompliance.conf <<BOOTSTRAPEOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

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
BOOTSTRAPEOF

        info "Starting nginx (port 80 needed for ACME challenge)..."
        $COMPOSE up -d nginx || {
            error "Failed to start nginx. Check if port 80 is already in use."
            error "Run: sudo lsof -i :80   or   sudo ss -tlnp | grep :80"
            exit 1
        }

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
                --non-interactive \
            || CERTBOT_EXIT=$?

        if [ "$CERTBOT_EXIT" -eq 0 ]; then
            # Cert obtained — write the real HTTPS config and reload nginx
            info "Writing full HTTPS nginx config..."
            cat > nginx/conf.d/mdcompliance.conf <<HTTPSEOF
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
    error_page 502 503 504 /502.html;
    location = /502.html {
        root /usr/share/nginx/error-pages;
        internal;
    }


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
HTTPSEOF
            info "Reloading nginx with HTTPS config..."
            $COMPOSE exec -T nginx nginx -s reload || docker exec nginx nginx -s reload || true
        fi
    fi

    if [ "$CERTBOT_EXIT" -eq 0 ]; then
        log "SSL certificate obtained for ${DOMAIN}"
    else
        error "Certbot failed."
        if [ "$SSL_METHOD" = "http" ]; then
            error "For HTTP challenge, check that:"
            error "  1. Port 80 is open and reachable from the internet"
            error "  2. ${DOMAIN} DNS A record points to this server (${SERVER_IP})"
            error "  3. No other service is using port 80"
            error ""
            error "If port 80 is blocked, re-run setup.sh and choose option 2 (DNS TXT)."
        else
            error "For DNS TXT challenge, check that:"
            error "  1. You added the _acme-challenge.${DOMAIN} TXT record"
            error "  2. The record had fully propagated before pressing Enter"
            error "  3. The TXT value you added matched the value shown on screen"
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
    error_page 502 503 504 /502.html;
    location = /502.html {
        root /usr/share/nginx/error-pages;
        internal;
    }

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

# Stop any existing containers from a previous run to avoid conflicts
if $COMPOSE ps -q 2>/dev/null | grep -q .; then
    info "Stopping existing containers from previous run..."
    $COMPOSE --profile production down 2>/dev/null || true
fi

info "Building and starting all services..."
if [ "$USE_SSL" = true ]; then
    $COMPOSE --profile production up -d --build || {
        error "Failed to start services. Check docker logs for details."
        exit 1
    }
else
    $COMPOSE up -d --build || {
        error "Failed to start services. Check docker logs for details."
        exit 1
    }
fi

info "Waiting for the app to be ready..."
sleep 8

# Health check
APP_UP=false
if [ "$USE_SSL" = true ]; then
    HEALTH_URL="http://localhost"
else
    HEALTH_URL="http://localhost:8000"
fi
for _ in {1..12}; do
    if curl -sf "$HEALTH_URL" &>/dev/null; then
        APP_UP=true
        break
    fi
    sleep 5
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
if [ "$APP_UP" = true ]; then
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${GREEN}║           MD Compliance is running!              ║${RESET}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${RESET}"
else
    echo -e "${BOLD}${YELLOW}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${YELLOW}║     MD Compliance started (may still be loading) ║${RESET}"
    echo -e "${BOLD}${YELLOW}╚══════════════════════════════════════════════════╝${RESET}"
    warn "Health check did not pass yet. The app may need more time to start."
    warn "Check logs: $COMPOSE logs -f app"
fi
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
echo "   View logs:          $COMPOSE logs -f app"
echo "   Stop:               $COMPOSE down"
echo "   Update app:         git pull && ./scripts/update.sh"
echo "   Backup database:    ./scripts/db-backup.sh"
echo ""
