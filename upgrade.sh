#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Safe Upgrade Script
#
# Usage:
#   ./upgrade.sh              # Pull latest code + rebuild + restart
#   ./upgrade.sh --backup     # Create DB backup first, then upgrade
#
# What this does:
#   1. (Optional) Creates a timestamped database backup
#   2. Pulls latest code from git
#   3. Rebuilds Docker containers (code only — NOT the database)
#   4. Restarts containers (run.sh auto-applies migrations)
#
# What is PRESERVED:
#   ✅ All database data (tenants, users, projects, controls, evidence)
#   ✅ Uploaded files (app_uploads Docker volume)
#   ✅ .env configuration file
#   ✅ SSL certificates (nginx/ssl/)
#   ✅ Browser localStorage (WISP drafts, tenant selection)
#
# What is UPDATED:
#   🔄 Application code (templates, routes, models)
#   🔄 Database schema (new columns/tables via Alembic migrations)
#   🔄 Static assets (CSS, JS)
#   🔄 Dependencies (pip install from requirements.txt)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

log()  { echo "[$(date -u +%H:%M:%S)] [INFO]    $*"; }
warn() { echo "[$(date -u +%H:%M:%S)] [WARNING] $*"; }
err()  { echo "[$(date -u +%H:%M:%S)] [ERROR]   $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env if present ─────────────────────────────────────────────────────
if [ -f .env ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")
        [ -n "$key" ] && export "$key=$value" 2>/dev/null || true
    done < .env
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-gapps}"

# ── Optional: Create backup ──────────────────────────────────────────────────
create_backup() {
    local backup_dir="$SCRIPT_DIR/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/db_backup_${timestamp}.sql"

    mkdir -p "$backup_dir"
    log "Creating database backup → $backup_file"

    if command -v docker &>/dev/null; then
        # Running in Docker environment — exec into postgres container
        docker exec postgres pg_dump \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            --no-owner \
            --no-acl \
            > "$backup_file" 2>/dev/null
    elif command -v pg_dump &>/dev/null; then
        # Running locally with pg_dump available
        PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
            -h "$POSTGRES_HOST" \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            --no-owner \
            --no-acl \
            > "$backup_file" 2>/dev/null
    else
        warn "Neither docker nor pg_dump available — skipping backup"
        return 0
    fi

    if [ $? -eq 0 ] && [ -s "$backup_file" ]; then
        local size=$(du -h "$backup_file" | cut -f1)
        log "Backup created: $backup_file ($size)"

        # Keep only last 10 backups
        ls -t "$backup_dir"/db_backup_*.sql 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null
        log "Retained last 10 backups"
    else
        warn "Backup may have failed — check $backup_file"
    fi
}

# ── Main upgrade flow ────────────────────────────────────────────────────────

log "═══════════════════════════════════════════════════"
log "  MD Compliance — Upgrade"
log "═══════════════════════════════════════════════════"

# Step 0: Optional backup
if [ "${1:-}" = "--backup" ]; then
    create_backup
fi

# Step 1: Pull latest code
log "Step 1/3: Pulling latest code..."
if git pull origin main; then
    log "Code updated"
else
    err "Git pull failed. Resolve conflicts manually, then re-run."
    exit 1
fi

# Step 2: Rebuild containers
log "Step 2/3: Rebuilding containers..."
# Prefer v2 plugin over v1 (v1.29.2 has ContainerConfig recreate bug)
DC=""
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC="docker-compose"
else
    warn "Docker not found — if running without Docker, restart the app manually"
    log "For non-Docker: pip install -r requirements.txt && flask db upgrade"
    exit 0
fi

$DC build --no-cache app

# Step 3: Restart (run.sh handles migrations automatically)
# Use down + up (not just up) to avoid docker-compose v1 recreate bug
log "Step 3/3: Restarting..."
$DC down 2>/dev/null || true
$DC up -d

log "═══════════════════════════════════════════════════"
log "  Upgrade complete!"
log ""
log "  Your data is safe. Migrations applied automatically."
log "  Check logs: docker-compose logs -f app"
log "═══════════════════════════════════════════════════"
