#!/bin/bash
# ============================================================
# restore-if-needed.sh (K8s / EKS version)
# ============================================================
# Runs at container startup BEFORE the main entrypoint.
# Restores PostgreSQL schema (foreign tables + TMF mappings)
# from whichever source is available:
#   1. S3 dump (mounted by init container)  → /mnt/dump/bssmagic-dump.sql.gz
#   2. Baked-in dump (baseline from build)  → /opt/bssmagic-dump.sql.gz
#   3. Neither → clean start (no restore)
#
# After successful restore, uploads the dump to S3 so future
# pods can pull the latest state (replaces EFS live snapshots).
#
# Idempotent: If the database already has foreign tables,
# the restore is skipped (pod restarted but PVC persisted).
# ============================================================

set -e

BAKED_DUMP="/opt/bssmagic-dump.sql.gz"
S3_DUMP="/mnt/dump/bssmagic-dump.sql.gz"
S3_DUMP_DIR="/mnt/dump"
DB_NAME="${POSTGRES_DB:-bssmagic}"
DB_USER="${POSTGRES_USER:-postgres}"

# S3 upload config (set by K8s env vars from operator)
DUMP_S3_BUCKET="${DUMP_S3_BUCKET:-}"
DUMP_S3_KEY="${DUMP_S3_KEY:-bssmagic-dump.sql.gz}"

MAX_WAIT=120
WAITED=0

log() { echo "[restore] $*"; }

# --- Wait for PostgreSQL ---
log "Waiting for PostgreSQL..."
while ! pg_isready -U "$DB_USER" -d "$DB_NAME" -q 2>/dev/null; do
  sleep 2
  WAITED=$((WAITED + 2))
  if [ $WAITED -ge $MAX_WAIT ]; then
    log "ERROR: PostgreSQL not ready after ${MAX_WAIT}s"
    exit 1
  fi
done
log "PostgreSQL ready (waited ${WAITED}s)"

# --- Wait for base image init to finish ---
# The base image's load_services.sh creates the foreign server, schemas, and types.
# We must wait for that to complete before restoring, otherwise our CREATE FOREIGN TABLE
# statements collide with concurrent schema/type creation and silently fail.
log "Waiting for base image init (foreign server creation)..."
while true; do
  SRV_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
    "SELECT count(*) FROM pg_foreign_server;" 2>/dev/null || echo "0")
  if [ "$SRV_COUNT" -gt 0 ] 2>/dev/null; then
    SRV_NAME=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
      "SELECT srvname FROM pg_foreign_server LIMIT 1;" 2>/dev/null || echo "unknown")
    log "Foreign server found: $SRV_NAME (base init complete)"
    break
  fi
  sleep 3
  WAITED=$((WAITED + 3))
  if [ $WAITED -ge $MAX_WAIT ]; then
    log "WARN: Timed out waiting for foreign server -- proceeding anyway"
    break
  fi
done

# Extra buffer for load_services.sh to finish creating types/schemas/user mappings.
log "Waiting 30s for load_services.sh to finish type/schema creation..."
sleep 30

# --- Check if restore is needed ---
# If foreign tables already exist, the database survived (PVC persisted)
FT_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT count(*) FROM pg_foreign_table;" 2>/dev/null || echo "0")

if [ "$FT_COUNT" -gt 10 ]; then
  log "Database already has $FT_COUNT foreign tables -- skipping restore"

  # Save a fresh dump to S3 if configured (live backup)
  if [ -n "$DUMP_S3_BUCKET" ]; then
    log "Taking live snapshot and uploading to S3..."
    pg_dump -U "$DB_USER" -d "$DB_NAME" --schema-only --no-owner --no-privileges \
      | gzip > "/tmp/bssmagic-dump.sql.gz.tmp" 2>/dev/null \
      && aws s3 cp "/tmp/bssmagic-dump.sql.gz.tmp" "s3://${DUMP_S3_BUCKET}/${DUMP_S3_KEY}" --quiet 2>/dev/null \
      && log "S3 snapshot uploaded" \
      && rm -f "/tmp/bssmagic-dump.sql.gz.tmp" \
      || log "WARN: S3 snapshot upload failed (non-fatal)"
  fi
  exit 0
fi

# --- Pick the dump source ---
DUMP_SOURCE=""
if [ -f "$S3_DUMP" ]; then
  DUMP_SOURCE="$S3_DUMP"
  log "Using S3 dump: $S3_DUMP ($(wc -c < "$S3_DUMP") bytes)"
elif [ -f "$BAKED_DUMP" ]; then
  DUMP_SOURCE="$BAKED_DUMP"
  log "Using baked-in dump: $BAKED_DUMP ($(wc -c < "$BAKED_DUMP") bytes)"
else
  log "No dump found -- clean start (no restore)"
  exit 0
fi

# --- Restore ---
log "Restoring from $DUMP_SOURCE..."

# Decompress and pipe to psql.
# ON_ERROR_STOP=off because some CREATE EXTENSION or role statements may already exist.
gunzip -c "$DUMP_SOURCE" | psql -U "$DB_USER" -d "$DB_NAME" \
  --set ON_ERROR_STOP=off \
  -q 2>&1 | tail -5

RESULT=${PIPESTATUS[1]}

# Verify restore
FT_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT count(*) FROM pg_foreign_table;" 2>/dev/null || echo "0")
VIEW_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT count(*) FROM information_schema.views WHERE table_schema='tmf';" 2>/dev/null || echo "0")
TRIGGER_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT count(*) FROM information_schema.triggers WHERE trigger_schema='tmf';" 2>/dev/null || echo "0")

log "Restore result: ${FT_COUNT} foreign tables, ${VIEW_COUNT} TMF views, ${TRIGGER_COUNT} TMF triggers"

if [ "$FT_COUNT" -gt 10 ]; then
  log "SUCCESS"

  # Upload restored dump to S3 (so future pods use the latest)
  if [ -n "$DUMP_S3_BUCKET" ] && [ "$DUMP_SOURCE" != "$S3_DUMP" ]; then
    log "Uploading baked-in dump to S3 for future use..."
    aws s3 cp "$DUMP_SOURCE" "s3://${DUMP_S3_BUCKET}/${DUMP_S3_KEY}" --quiet 2>/dev/null \
      && log "Uploaded to s3://${DUMP_S3_BUCKET}/${DUMP_S3_KEY}" \
      || log "WARN: S3 upload failed (non-fatal)"
  fi
else
  log "WARNING: Only $FT_COUNT foreign tables after restore -- may be incomplete"
fi
