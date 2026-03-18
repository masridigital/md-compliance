#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — SSL Certificate Renewal
#
# Certificates renew automatically every 12 hours via the certbot container.
# Run this manually to force an immediate renewal check.
#
# Usage: ./scripts/renew-ssl.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }

# Detect compose command
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

log "Forcing SSL certificate renewal check..."
$COMPOSE exec certbot certbot renew --quiet --webroot --webroot-path=/var/www/certbot

log "Reloading nginx to pick up any new certificates..."
$COMPOSE exec nginx nginx -s reload

log "Done. Run 'docker-compose exec certbot certbot certificates' to check expiry dates."
