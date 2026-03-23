#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — SSL Certificate Renewal
#
# Certificates renew automatically every 12 hours via the certbot container
# when using the HTTP (webroot) method.
#
# If your certificate was issued using the DNS challenge, automated renewal
# also requires manual DNS interaction. Use --force-dns below to re-issue.
#
# Usage:
#   ./scripts/renew-ssl.sh              # standard webroot renewal
#   ./scripts/renew-ssl.sh --dns        # manual DNS-01 re-issue (interactive)
#   ./scripts/renew-ssl.sh --status     # show certificate expiry info
# ─────────────────────────────────────────────────────────────────────────────

set -e

log()   { echo "[$(date -u +%H:%M:%S)] $*"; }
warn()  { echo "[!] $*"; }
error() { echo "[✗] $*" >&2; }

# Detect compose command
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

# Read domain from .env if available
DOMAIN=""
if [ -f .env ]; then
    DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2 | tr -d '"' | tr -d "'")
fi

# ── Parse arguments ───────────────────────────────────────────────────────────
MODE="webroot"
for arg in "$@"; do
    case "$arg" in
        --dns)      MODE="dns" ;;
        --status)   MODE="status" ;;
        --help|-h)
            echo "Usage: $0 [--dns|--status|--help]"
            echo ""
            echo "  (no flag)  Renew via HTTP webroot (default, non-interactive)"
            echo "  --dns      Re-issue certificate via DNS TXT record (interactive)"
            echo "  --status   Show certificate expiry dates"
            exit 0
            ;;
    esac
done

# ── Status ────────────────────────────────────────────────────────────────────
if [ "$MODE" = "status" ]; then
    log "Certificate status:"
    $COMPOSE exec certbot certbot certificates 2>/dev/null \
        || docker run --rm \
            -v "$(pwd)/nginx/ssl/letsencrypt:/etc/letsencrypt" \
            certbot/certbot certificates
    exit 0
fi

# ── DNS-01 manual re-issue ────────────────────────────────────────────────────
if [ "$MODE" = "dns" ]; then
    if [ -z "$DOMAIN" ]; then
        warn "Could not read DOMAIN from .env — you will be prompted by Certbot."
    else
        log "Re-issuing certificate for ${DOMAIN} via DNS-01 challenge..."
        echo ""
        warn "Certbot will display a TXT record to add to your DNS."
        warn "Do NOT press Enter until the record has propagated."
        echo ""
    fi

    EMAIL_ARG=""
    if [ -f .env ]; then
        CERTBOT_EMAIL=$(grep -E '^CERTBOT_EMAIL=' .env | cut -d= -f2 | tr -d '"' | tr -d "'" 2>/dev/null || true)
        [ -n "$CERTBOT_EMAIL" ] && EMAIL_ARG="--email ${CERTBOT_EMAIL}"
    fi

    docker run -it --rm \
        -v "$(pwd)/nginx/ssl/letsencrypt:/etc/letsencrypt" \
        certbot/certbot certonly \
            --manual \
            --preferred-challenges dns \
            ${EMAIL_ARG} \
            --agree-tos \
            --no-eff-email \
            ${DOMAIN:+-d "$DOMAIN"}

    log "Reloading nginx to pick up new certificate..."
    $COMPOSE exec nginx nginx -s reload 2>/dev/null || true
    log "Done."
    exit 0
fi

# ── HTTP-01 webroot renewal (default) ─────────────────────────────────────────
log "Forcing SSL certificate renewal check (webroot)..."

# Try via running certbot container first, fall back to docker run
if $COMPOSE ps certbot 2>/dev/null | grep -q "Up"; then
    $COMPOSE exec certbot certbot renew --quiet --webroot --webroot-path=/var/www/certbot
else
    docker run --rm \
        -v "$(pwd)/nginx/ssl/letsencrypt:/etc/letsencrypt" \
        -v "$(pwd)/nginx/certbot-webroot:/var/www/certbot" \
        certbot/certbot renew --quiet --webroot --webroot-path=/var/www/certbot
fi

log "Reloading nginx to pick up any new certificates..."
$COMPOSE exec nginx nginx -s reload

log "Done. Run '$0 --status' to check expiry dates."
