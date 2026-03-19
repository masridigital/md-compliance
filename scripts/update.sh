#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Application Update Script
#
# Pulls latest code and restarts. Your database is never touched.
#
# Usage: ./scripts/update.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
warn() { echo "[$(date -u +%H:%M:%S)] [!] $*"; }

# Detect compose command
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

log "MD Compliance — Update"
log "━━━━━━━━━━━━━━━━━━━━━━"

# 1. Back up the database first
log "Creating pre-update backup..."
./scripts/db-backup.sh
log "Backup complete"

# 2. Pull latest code
log "Pulling latest code from GitHub..."
git pull origin main

# 3. Rebuild and restart (migrations run automatically on startup)
log "Rebuilding and restarting services..."
$COMPOSE up -d --build

log "━━━━━━━━━━━━━━━━━━━━━━"
log "Update complete."
log ""
log "The app is applying any new database migrations automatically."
log "Check logs: docker-compose logs -f app"
