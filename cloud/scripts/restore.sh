#!/usr/bin/env bash
# AWT Cloud — Database & Screenshots Restore
# Usage: ./restore.sh <backup_dir>
#
# Restores from a backup created by backup.sh:
#   1. SQLite database (awt_cloud.db)
#   2. Screenshots directory
#   3. Uploads directory
#
# IMPORTANT: Stop the server before restoring!

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup_dir>"
    echo ""
    echo "Example: $0 ./backups/20260217_120000"
    echo ""
    # List available backups
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    CLOUD_DIR="$(dirname "$SCRIPT_DIR")"
    BACKUP_ROOT="${CLOUD_DIR}/backups"
    if [ -d "${BACKUP_ROOT}" ]; then
        echo "Available backups:"
        find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | sort -r | while read -r dir; do
            echo "  $(basename "$dir")  ($(du -sh "$dir" 2>/dev/null | cut -f1))"
        done
    fi
    exit 1
fi

BACKUP_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLOUD_DIR="$(dirname "$SCRIPT_DIR")"

DB_FILE="${CLOUD_DIR}/awt_cloud.db"
SCREENSHOT_DIR="${CLOUD_DIR}/screenshots"
UPLOAD_DIR="${CLOUD_DIR}/uploads"

if [ ! -d "${BACKUP_DIR}" ]; then
    echo "Error: Backup directory not found: ${BACKUP_DIR}"
    exit 1
fi

echo "=== AWT Cloud Restore ==="
echo "From: ${BACKUP_DIR}"
echo "To:   ${CLOUD_DIR}"
echo ""
echo "WARNING: This will overwrite existing data!"
read -p "Continue? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# 1. Database restore
if [ -f "${BACKUP_DIR}/awt_cloud.db" ]; then
    echo "[1/3] Restoring database..."
    if [ -f "${DB_FILE}" ]; then
        cp "${DB_FILE}" "${DB_FILE}.pre-restore"
        echo "  -> Old DB saved as awt_cloud.db.pre-restore"
    fi
    cp "${BACKUP_DIR}/awt_cloud.db" "${DB_FILE}"
    echo "  -> Database restored"
else
    echo "[1/3] No database in backup, skipping."
fi

# 2. Screenshots restore
if [ -f "${BACKUP_DIR}/screenshots.tar.gz" ]; then
    echo "[2/3] Restoring screenshots..."
    mkdir -p "$(dirname "${SCREENSHOT_DIR}")"
    tar xzf "${BACKUP_DIR}/screenshots.tar.gz" -C "$(dirname "${SCREENSHOT_DIR}")"
    echo "  -> Screenshots restored"
else
    echo "[2/3] No screenshots in backup, skipping."
fi

# 3. Uploads restore
if [ -f "${BACKUP_DIR}/uploads.tar.gz" ]; then
    echo "[3/3] Restoring uploads..."
    mkdir -p "$(dirname "${UPLOAD_DIR}")"
    tar xzf "${BACKUP_DIR}/uploads.tar.gz" -C "$(dirname "${UPLOAD_DIR}")"
    echo "  -> Uploads restored"
else
    echo "[3/3] No uploads in backup, skipping."
fi

echo ""
echo "Restore complete. Start the server to verify."
