#!/bin/bash
# ============================================================
# apply-tmf-mappings.sh
# ============================================================
# Applies TMF view/trigger mapping SQL files to the BSSMagic
# PostgreSQL database after restore completes.
#
# Runs after restore-if-needed.sh. Waits for:
#   1. PostgreSQL to be ready
#   2. Foreign tables to exist (restore complete)
#
# Views are created in the 'mapping' schema (product convention).
# Trigger functions are also placed in the 'mapping' schema.
#
# Idempotent: uses DROP VIEW CASCADE + CREATE VIEW / CREATE OR
# REPLACE FUNCTION, so re-running is safe. DROP CASCADE is
# required because CREATE OR REPLACE VIEW cannot reorder columns.
# ============================================================

set -e

MAPPINGS_DIR="/opt/tmf-mappings"
DB_NAME="${POSTGRES_DB:-bssmagic}"
DB_USER="${POSTGRES_USER:-postgres}"
MAX_WAIT=300
WAITED=0

log() { echo "[tmf-mappings] $*"; }

# Skip if no mappings directory
if [ ! -d "$MAPPINGS_DIR" ] || [ -z "$(ls -A "$MAPPINGS_DIR" 2>/dev/null)" ]; then
    log "No TMF mappings found at $MAPPINGS_DIR -- skipping"
    exit 0
fi

# --- Wait for PostgreSQL ---
log "Waiting for PostgreSQL..."
while ! pg_isready -U "$DB_USER" -d "$DB_NAME" -q 2>/dev/null; do
    sleep 3
    WAITED=$((WAITED + 3))
    if [ $WAITED -ge $MAX_WAIT ]; then
        log "ERROR: PostgreSQL not ready after ${MAX_WAIT}s"
        exit 1
    fi
done
log "PostgreSQL ready (waited ${WAITED}s)"

# --- Wait for restore to complete (foreign tables must exist) ---
log "Waiting for DB restore to complete..."
while true; do
    FT_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
        "SELECT count(*) FROM pg_foreign_table;" 2>/dev/null || echo "0")
    if [ "$FT_COUNT" -gt 10 ] 2>/dev/null; then
        log "Foreign tables found: $FT_COUNT (restore complete)"
        break
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    if [ $WAITED -ge $MAX_WAIT ]; then
        log "WARN: Timed out waiting for foreign tables -- applying anyway"
        break
    fi
done

# --- Ensure mapping schema exists (product convention) ---
psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE SCHEMA IF NOT EXISTS mapping;" -q 2>/dev/null

# --- Set search_path so TMF Server finds views without schema prefix ---
psql -U "$DB_USER" -d "$DB_NAME" -c "ALTER DATABASE $DB_NAME SET search_path = public, mapping;" -q 2>/dev/null
log "search_path set to: public, mapping"

# --- Apply each mapping file ---
APPLIED=0
FAILED=0
for sql_file in "$MAPPINGS_DIR"/*.sql; do
    [ -f "$sql_file" ] || continue
    fname=$(basename "$sql_file")
    log "Applying $fname..."
    OUTPUT=$(psql -U "$DB_USER" -d "$DB_NAME" -f "$sql_file" 2>&1)
    EXIT_CODE=$?
    echo "$OUTPUT" | tail -5
    if [ $EXIT_CODE -eq 0 ] && ! echo "$OUTPUT" | grep -qi "ERROR:"; then
        APPLIED=$((APPLIED + 1))
    else
        log "WARN: $fname had errors (non-fatal). Check output above."
        FAILED=$((FAILED + 1))
    fi
done

# --- Verify ---
VIEW_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
    "SELECT count(*) FROM information_schema.views WHERE table_schema='mapping';" 2>/dev/null || echo "0")
TRIGGER_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
    "SELECT count(*) FROM information_schema.triggers WHERE trigger_schema='mapping';" 2>/dev/null || echo "0")

log "Done: applied=$APPLIED failed=$FAILED views=$VIEW_COUNT triggers=$TRIGGER_COUNT"
