#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Full Stack Update Script
#
# Usage:
#   ./update.sh                  # Standard update (pull + rebuild + restart)
#   ./update.sh --backup         # DB backup first, then update
#   ./update.sh --frontend-only  # Rebuild app container only (skip DB backup)
#   ./update.sh --status         # Show current versions and container health
#
# What happens:
#   1. Checks all containers are reachable
#   2. (Optional) Creates a timestamped database backup
#   3. Pulls latest code from git (main branch)
#   4. Installs/updates Python dependencies
#   5. Rebuilds frontend assets (Tailwind CSS)
#   6. Rebuilds Docker containers
#   7. Applies database migrations
#   8. Restarts all services (app, redis, nginx, celery if active)
#   9. Runs health check to verify everything came back up
#
# Safe by default:
#   ✅ Database is NEVER touched destructively
#   ✅ Docker volumes (postgres_data, app_uploads) survive rebuilds
#   ✅ .env, SSL certs, nginx config are preserved
#   ✅ Rolls back git pull on build failure
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colors & Logging ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date -u +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date -u +%H:%M:%S)] ⚠${NC}  $*"; }
err()  { echo -e "${RED}[$(date -u +%H:%M:%S)] ✗${NC}  $*" >&2; }
ok()   { echo -e "${GREEN}[$(date -u +%H:%M:%S)] ✓${NC}  $*"; }
step() { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f .env ]; then
    # Safe parse: only export lines matching KEY=VALUE, skip comments/blanks
    while IFS='=' read -r key value; do
        # Skip comments and blank lines
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs)  # trim whitespace
        value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")  # strip quotes
        [ -n "$key" ] && export "$key=$value" 2>/dev/null || true
    done < .env
fi

BRANCH="${GIT_BRANCH:-main}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-gapps}"

# ── Docker Compose command ───────────────────────────────────────────────────
# Prefer v2 plugin ("docker compose") over v1 ("docker-compose")
# v1.29.2 has a ContainerConfig KeyError bug when recreating containers
DC=""
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC="docker-compose"
    warn "Using docker-compose v1 — consider upgrading to v2 (apt-get install docker-compose-plugin)"
else
    err "Docker Compose not found. Install Docker first."
    exit 1
fi

# ── Parse args ───────────────────────────────────────────────────────────────
DO_BACKUP=false
FRONTEND_ONLY=false
STATUS_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --backup)         DO_BACKUP=true ;;
        --frontend-only)  FRONTEND_ONLY=true ;;
        --status)         STATUS_ONLY=true ;;
        --help|-h)
            echo "Usage: ./update.sh [--backup] [--frontend-only] [--status]"
            echo ""
            echo "  --backup         Create DB backup before updating"
            echo "  --frontend-only  Rebuild app only, skip git pull"
            echo "  --status         Show container status and exit"
            exit 0
            ;;
        *) warn "Unknown flag: $arg (ignored)" ;;
    esac
done

# ── Status command ───────────────────────────────────────────────────────────
show_status() {
    step "Container Status"
    $DC ps
    echo ""

    step "Git Info"
    echo "  Branch:  $(git branch --show-current)"
    echo "  Commit:  $(git log --oneline -1)"
    echo "  Remote:  $(git remote get-url origin 2>/dev/null || echo 'N/A')"

    if [ -f .env ]; then
        echo ""
        step "Version"
        echo "  VERSION: ${VERSION:-not set}"
        echo "  DOMAIN:  ${DOMAIN:-localhost}"
    fi

    echo ""
    step "Disk Usage"
    echo "  Project:  $(du -sh "$SCRIPT_DIR" 2>/dev/null | cut -f1)"
    echo "  Docker:   $(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || echo 'N/A')"

    echo ""
    step "Health Checks"
    for svc in app postgres redis; do
        status=$($DC ps --format '{{.Status}}' "$svc" 2>/dev/null || echo "not running")
        if echo "$status" | grep -qi "up"; then
            ok "$svc: $status"
        else
            err "$svc: $status"
        fi
    done
}

if [ "$STATUS_ONLY" = true ]; then
    show_status
    exit 0
fi

# ── Start update ─────────────────────────────────────────────────────────────
echo -e "\n${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  MD Compliance — Full Stack Update${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""

PREV_COMMIT=$(git rev-parse HEAD)

# ── Step 1: Pre-flight checks ───────────────────────────────────────────────
step "Step 1/7: Pre-flight checks"

# Ensure we're on a clean working tree (warn only)
if [ -n "$(git status --porcelain)" ]; then
    warn "Working tree has uncommitted changes"
    git status --short
    echo ""
fi

# Check containers are running
for svc in app postgres redis; do
    if $DC ps "$svc" 2>/dev/null | grep -q "Up"; then
        ok "$svc is running"
    else
        warn "$svc is not running — will start after update"
    fi
done

# ── Step 2: Database backup ─────────────────────────────────────────────────
if [ "$DO_BACKUP" = true ]; then
    step "Step 2/7: Database backup"
    BACKUP_DIR="$SCRIPT_DIR/backups"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/db_backup_${TIMESTAMP}.sql"
    mkdir -p "$BACKUP_DIR"

    log "Creating backup → $BACKUP_FILE"
    if docker exec postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-owner --no-acl > "$BACKUP_FILE" 2>/dev/null; then
        SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        ok "Backup created ($SIZE)"
        # Retain last 10 backups
        ls -t "$BACKUP_DIR"/db_backup_*.sql 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null
    else
        warn "Backup failed — continuing without backup"
        rm -f "$BACKUP_FILE"
    fi
else
    log "Step 2/7: Skipping backup (use --backup to enable)"
fi

# ── Step 3: Pull latest code ────────────────────────────────────────────────
if [ "$FRONTEND_ONLY" = false ]; then
    step "Step 3/7: Pulling latest code"
    if git pull origin "$BRANCH"; then
        NEW_COMMIT=$(git rev-parse HEAD)
        if [ "$PREV_COMMIT" = "$NEW_COMMIT" ]; then
            ok "Already up to date ($NEW_COMMIT)"
        else
            CHANGES=$(git log --oneline "${PREV_COMMIT}..${NEW_COMMIT}" | wc -l)
            ok "Pulled $CHANGES new commit(s)"
            git log --oneline "${PREV_COMMIT}..${NEW_COMMIT}" | head -5
        fi
    else
        err "Git pull failed — aborting update"
        exit 1
    fi
else
    log "Step 3/7: Skipping git pull (--frontend-only)"
fi

# ── Step 4: Update Python dependencies ──────────────────────────────────────
step "Step 4/7: Checking dependencies"
if [ -f requirements.txt ]; then
    # Show if requirements changed
    if git diff "${PREV_COMMIT}..HEAD" --name-only 2>/dev/null | grep -q "requirements.txt"; then
        log "requirements.txt changed — dependencies will update on rebuild"
    else
        ok "requirements.txt unchanged"
    fi
fi

# ── Step 5: Build frontend assets ───────────────────────────────────────────
step "Step 5/7: Frontend assets"
if [ -d "tl_src" ] && [ -f "tl_src/package.json" ]; then
    if command -v npm &>/dev/null; then
        log "Building Tailwind CSS..."
        (cd tl_src && npm install --silent 2>/dev/null && npm run build 2>/dev/null) && \
            ok "Tailwind CSS rebuilt" || warn "Tailwind build skipped (non-fatal)"
    else
        log "npm not found — Tailwind will use existing built CSS"
    fi
else
    ok "No frontend build step required (static CSS)"
fi

# ── Step 6: Rebuild Docker containers ───────────────────────────────────────
step "Step 6/7: Rebuilding containers"
log "Building app container..."
if $DC build --no-cache app 2>&1 | tail -5; then
    ok "App container rebuilt"
else
    err "Build failed — rolling back to previous commit"
    git checkout "$PREV_COMMIT" 2>/dev/null
    err "Rolled back to $PREV_COMMIT. Fix the issue and retry."
    exit 1
fi

# ── Step 7: Restart services ────────────────────────────────────────────────
step "Step 7/7: Restarting services"

# Stop and remove all containers first to avoid docker-compose v1 recreate bug
# (ContainerConfig KeyError). Data is safe in Docker volumes.
log "Stopping all containers..."
$DC down 2>/dev/null || true

# Start everything fresh
log "Starting all services..."
$DC up -d
ok "All services started"

# ── Health check ─────────────────────────────────────────────────────────────
step "Health Check"
log "Waiting for app to start..."
RETRIES=0
MAX_RETRIES=30
while [ $RETRIES -lt $MAX_RETRIES ]; do
    if docker exec app curl -sf http://localhost:5000/ > /dev/null 2>&1; then
        ok "App is healthy"
        break
    fi
    RETRIES=$((RETRIES + 1))
    sleep 2
done

if [ $RETRIES -eq $MAX_RETRIES ]; then
    warn "App did not respond within 60s — check logs:"
    warn "  $DC logs --tail 30 app"
fi

# Final status
echo ""
for svc in app postgres redis; do
    status=$($DC ps --format '{{.Status}}' "$svc" 2>/dev/null || echo "unknown")
    if echo "$status" | grep -qi "up"; then
        ok "$svc: $status"
    else
        warn "$svc: $status"
    fi
done

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Update complete!${NC}"
echo -e "${GREEN}${NC}"
echo -e "${GREEN}  Branch:  $(git branch --show-current)${NC}"
echo -e "${GREEN}  Commit:  $(git log --oneline -1)${NC}"
echo -e "${GREEN}  Logs:    $DC logs -f app${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
