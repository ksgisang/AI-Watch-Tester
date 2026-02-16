#!/usr/bin/env bash
# AWT Cloud — Database & Screenshots Backup
# Usage: ./backup.sh [backup_dir]
#
# Creates a timestamped backup of:
#   1. SQLite database (awt_cloud.db)
#   2. Screenshots directory
#   3. Uploads directory
#
# Default backup location: ./backups/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLOUD_DIR="$(dirname "$SCRIPT_DIR")"

BACKUP_ROOT="${1:-${CLOUD_DIR}/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

DB_FILE="${CLOUD_DIR}/awt_cloud.db"
SCREENSHOT_DIR="${CLOUD_DIR}/cloud/screenshots"
UPLOAD_DIR="${CLOUD_DIR}/cloud/uploads"

echo "=== AWT Cloud Backup ==="
echo "Timestamp: ${TIMESTAMP}"
echo "Backup to: ${BACKUP_DIR}"
echo ""

mkdir -p "${BACKUP_DIR}"

# 1. Database backup
if [ -f "${DB_FILE}" ]; then
    echo "[1/3] Backing up database..."
    # Use sqlite3 .backup for consistent snapshot (if available)
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "${DB_FILE}" ".backup '${BACKUP_DIR}/awt_cloud.db'"
    else
        cp "${DB_FILE}" "${BACKUP_DIR}/awt_cloud.db"
    fi
    echo "  -> awt_cloud.db ($(du -h "${BACKUP_DIR}/awt_cloud.db" | cut -f1))"
else
    echo "[1/3] No database file found at ${DB_FILE}, skipping."
fi

# 2. Screenshots backup
if [ -d "${SCREENSHOT_DIR}" ]; then
    echo "[2/3] Backing up screenshots..."
    tar czf "${BACKUP_DIR}/screenshots.tar.gz" -C "$(dirname "${SCREENSHOT_DIR}")" "$(basename "${SCREENSHOT_DIR}")" 2>/dev/null || true
    echo "  -> screenshots.tar.gz ($(du -h "${BACKUP_DIR}/screenshots.tar.gz" 2>/dev/null | cut -f1 || echo '0'))"
else
    echo "[2/3] No screenshots directory, skipping."
fi

# 3. Uploads backup
if [ -d "${UPLOAD_DIR}" ]; then
    echo "[3/3] Backing up uploads..."
    tar czf "${BACKUP_DIR}/uploads.tar.gz" -C "$(dirname "${UPLOAD_DIR}")" "$(basename "${UPLOAD_DIR}")" 2>/dev/null || true
    echo "  -> uploads.tar.gz ($(du -h "${BACKUP_DIR}/uploads.tar.gz" 2>/dev/null | cut -f1 || echo '0'))"
else
    echo "[3/3] No uploads directory, skipping."
fi

# Summary
echo ""
echo "Backup complete: ${BACKUP_DIR}"
ls -lh "${BACKUP_DIR}/"
echo ""

# Retention: keep last 7 backups, delete older ones
BACKUP_COUNT=$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
if [ "${BACKUP_COUNT}" -gt 7 ]; then
    echo "Cleaning old backups (keeping last 7)..."
    find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | sort | head -n -7 | xargs rm -rf
    echo "Done."
fi
