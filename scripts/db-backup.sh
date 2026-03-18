#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MD Compliance — Database Backup Helper
#
# Usage:
#   ./scripts/db-backup.sh              # Backup to ./backups/ with timestamp
#   ./scripts/db-backup.sh /path/to/dir # Backup to a specific directory
#
# Restore a backup:
#   ./scripts/db-restore.sh backups/mdcompliance_2026-03-17_120000.sql.gz
# ─────────────────────────────────────────────────────────────────────────────

set -e

BACKUP_DIR=${1:-./backups}
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
DB_NAME=${POSTGRES_DB:-db1}
DB_USER=${POSTGRES_USER:-db1}
FILENAME="${BACKUP_DIR}/mdcompliance_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -u +%H:%M:%S)] Starting backup → $FILENAME"

docker-compose exec -T postgres \
    pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$FILENAME"

SIZE=$(du -sh "$FILENAME" | cut -f1)
echo "[$(date -u +%H:%M:%S)] Backup complete — $FILENAME ($SIZE)"
