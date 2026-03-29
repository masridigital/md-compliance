#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Application Entrypoint
#
# Startup sequence:
#   1. Wait for PostgreSQL to be ready
#   2. Fresh install:  run init_db + stamp migrations to head
#      Existing DB:    run `flask db upgrade` to apply any new migrations
#   3. Start Gunicorn
#
# IMPORTANT — data safety:
#   • `git pull` + `docker-compose up -d --build` will NEVER wipe the database
#   • The only way to erase data is: RESET_DB=yes  (requires explicit opt-in)
#   • The postgres_data Docker volume keeps data across all restarts and rebuilds
# ─────────────────────────────────────────────────────────────────────────────

set -e

PORT=${PORT:-5000}
GUNICORN_WORKERS=${GUNICORN_WORKERS:-2}
GUNICORN_THREADS=${GUNICORN_THREADS:-1}
GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-120}
GUNICORN_KEEP_ALIVE=${GUNICORN_KEEP_ALIVE:-60}

# ── Helpers ───────────────────────────────────────────────────────────────────

log()  { echo "[$(date -u +%H:%M:%S)] [INFO]    $*"; }
warn() { echo "[$(date -u +%H:%M:%S)] [WARNING] $*"; }
err()  { echo "[$(date -u +%H:%M:%S)] [ERROR]   $*" >&2; }

start_server() {
    log "Starting Gunicorn with $GUNICORN_WORKERS worker(s) on port $PORT"
    exec gunicorn \
        --bind "0.0.0.0:$PORT" \
        flask_app:app \
        --access-logfile '-' \
        --error-logfile '-' \
        --workers="$GUNICORN_WORKERS" \
        --threads="$GUNICORN_THREADS" \
        --timeout="$GUNICORN_TIMEOUT" \
        --keep-alive="$GUNICORN_KEEP_ALIVE"
}

wait_for_db() {
    log "Waiting for PostgreSQL..."
    until python3 tools/check_db_connection.py 2>/dev/null; do
        warn "Database unavailable — retrying in 3s..."
        sleep 3
    done
    log "PostgreSQL is ready"
}

db_is_initialized() {
    # Returns 0 (true) if the database already has the core gapps tables
    python3 - <<'EOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")
from app import create_app, db
from sqlalchemy import inspect

app = create_app(os.getenv("FLASK_CONFIG") or "default")
with app.app_context():
    try:
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        # Consider initialized if we have at least the tenant and user tables
        sys.exit(0 if len(tables) >= 5 else 1)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
EOF
}

stamp_migrations_to_head() {
    # Tell Alembic "this DB is already at the latest migration" without
    # re-running any DDL. Used when we detect an existing database that
    # was created before Alembic was introduced.
    log "Stamping migration history to head (existing database detected)"
    python3 -c "
import os
from app import create_app, db
from flask_migrate import stamp
app = create_app(os.getenv('FLASK_CONFIG') or 'default')
with app.app_context():
    stamp()
"
    log "Migration history stamped"
}

run_migrations() {
    log "Running database migrations (flask db upgrade)..."
    python3 -c "
import os
from app import create_app, db
from flask_migrate import upgrade
app = create_app(os.getenv('FLASK_CONFIG') or 'default')
with app.app_context():
    upgrade()
"
    log "Migrations complete"
}

initialize_fresh_db() {
    log "Fresh database detected — initializing schema..."
    python3 manage.py init_db
    log "Schema created"
    stamp_migrations_to_head
}

reset_db() {
    warn "⚠  RESET_DB=yes detected — ALL DATA WILL BE ERASED"
    warn "⚠  Waiting 10 seconds before proceeding... (Ctrl-C to abort)"
    sleep 10
    python3 manage.py init_db
    log "Database reset complete"
    stamp_migrations_to_head
}

# ── Main startup ──────────────────────────────────────────────────────────────

if [ "$SKIP_INI_CHECKS" = "yes" ]; then
    log "SKIP_INI_CHECKS=yes — skipping database checks"
    start_server
fi

wait_for_db

if [ "$RESET_DB" = "yes" ]; then
    # Explicit wipe — user must set this intentionally
    reset_db
elif db_is_initialized; then
    # ── Existing database: apply any new migrations ──────────────────────────
    # This is the normal path on every `git pull` + rebuild.
    # New columns/tables from new migrations are applied safely.
    # No existing data is touched.
    log "Existing database detected"

    # Check if migration history table exists; if not, stamp first
    if ! python3 - <<'EOF'
import sys, os
sys.path.insert(0, ".")
from app import create_app, db
from sqlalchemy import inspect
app = create_app(os.getenv("FLASK_CONFIG") or "default")
with app.app_context():
    inspector = inspect(db.engine)
    sys.exit(0 if "alembic_version" in inspector.get_table_names() else 1)
EOF
    then
        warn "No migration history found on existing database — stamping to head first"
        stamp_migrations_to_head
    fi

    run_migrations
else
    # ── Fresh database: create schema + stamp ────────────────────────────────
    initialize_fresh_db
fi

if [ "$ONESHOT" = "yes" ]; then
    log "ONESHOT mode — exiting after DB setup"
    exit 0
fi

start_server
