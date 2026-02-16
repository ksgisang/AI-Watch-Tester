# Backup & Recovery Guide

## Overview

AWT Cloud stores data in three locations:

| Data | Location | Description |
|------|----------|-------------|
| Database | `awt_cloud.db` | Test records, user data, scenarios |
| Screenshots | `cloud/screenshots/` | Before/after screenshots per test |
| Uploads | `cloud/uploads/` | Uploaded spec documents |

## Quick Start

```bash
# Backup
./scripts/backup.sh

# Restore (stop server first!)
./scripts/restore.sh ./backups/20260217_120000
```

## Backup

### Manual Backup

```bash
cd cloud/
./scripts/backup.sh
```

Creates a timestamped directory under `backups/`:
```
backups/
  20260217_120000/
    awt_cloud.db          # SQLite database snapshot
    screenshots.tar.gz    # Compressed screenshots
    uploads.tar.gz        # Compressed uploads
```

### Custom Backup Location

```bash
./scripts/backup.sh /path/to/backup/dir
```

### Automated Backup (cron)

```bash
# Daily at 2 AM
0 2 * * * cd /path/to/cloud && ./scripts/backup.sh >> /var/log/awt-backup.log 2>&1
```

### Retention

The backup script automatically keeps the **last 7 backups** and deletes older ones.

## Restore

**Important:** Stop the server before restoring.

```bash
# 1. Stop the server
# 2. List available backups
./scripts/restore.sh

# 3. Restore from a specific backup
./scripts/restore.sh ./backups/20260217_120000

# 4. Start the server
uvicorn app.main:app --host :: --port 8000
```

The restore script:
- Saves the current database as `awt_cloud.db.pre-restore` before overwriting
- Asks for confirmation before proceeding
- Restores database, screenshots, and uploads

## PostgreSQL (Production)

For production deployments using PostgreSQL (Supabase):

```bash
# Backup
pg_dump $DATABASE_URL > backup.sql

# Restore
psql $DATABASE_URL < backup.sql
```

Screenshots and uploads are still file-based and should be backed up separately, or use cloud storage (S3/GCS) for production.
