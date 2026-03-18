#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Database Restore Helper
#
# Usage:
#   ./scripts/db-restore.sh backups/mdcompliance_2026-03-17_120000.sql.gz
# ─────────────────────────────────────────────────────────────────────────────

set -e

BACKUP_FILE=$1
DB_NAME=${POSTGRES_DB:-db1}
DB_USER=${POSTGRES_USER:-db1}

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "[ERROR] File not found: $BACKUP_FILE"
    exit 1
fi

echo "[WARNING] This will REPLACE the current database with the backup."
echo "[WARNING] File: $BACKUP_FILE"
read -p "Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo "[$(date -u +%H:%M:%S)] Restoring from $BACKUP_FILE..."

gunzip -c "$BACKUP_FILE" | docker-compose exec -T postgres \
    psql -U "$DB_USER" "$DB_NAME"

echo "[$(date -u +%H:%M:%S)] Restore complete."
