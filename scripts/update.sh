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

# 2. Pull latest code — fetch then reset so divergent local state never blocks
BRANCH=$(git rev-parse --abbrev-ref HEAD)
log "Pulling latest code (branch: $BRANCH)..."
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
log "Code updated"

# 3. Rebuild and restart (migrations run automatically on startup)
log "Rebuilding and restarting services..."
$COMPOSE --profile production up -d --build

log "━━━━━━━━━━━━━━━━━━━━━━"
log "Update complete."
log ""
log "The app is applying any new database migrations automatically."
log "Check logs: docker compose logs -f app"
