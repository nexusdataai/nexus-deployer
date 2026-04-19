#!/bin/bash
# ============================================================
# start-tmf-rest-api.sh
# ============================================================
# Starts the TMF REST API gateway on port 8000.
# This is the single external-facing API port. It proxies reads
# to the product TMF Server on port 8001 (internal) and handles
# /query and writes locally.
#
# Includes a restart loop: if the Python process crashes, it
# restarts automatically after a brief delay.
# ============================================================

DB_NAME="${POSTGRES_DB:-bssmagic}"
DB_USER="${POSTGRES_USER:-postgres}"
TMF_PORT="${TMF_REST_API_PORT:-8000}"

MAX_WAIT=180
WAITED=0

log() { echo "[tmf-rest-api] $*"; }

# --- Wait for PostgreSQL ---
log "Waiting for PostgreSQL before starting TMF REST API gateway..."
while ! pg_isready -U "$DB_USER" -d "$DB_NAME" -q 2>/dev/null; do
  sleep 3
  WAITED=$((WAITED + 3))
  if [ $WAITED -ge $MAX_WAIT ]; then
    log "ERROR: PostgreSQL not ready after ${MAX_WAIT}s -- skipping TMF REST API"
    exit 1
  fi
done

# Wait for database restore to complete
log "Waiting 60s for database restore to complete..."
sleep 60

# --- Start TMF REST API with auto-restart ---
log "Starting TMF REST API gateway on port ${TMF_PORT} with auto-restart..."
while true; do
    python3 /usr/local/bin/tmf-rest-api.py "$TMF_PORT"
    EXIT_CODE=$?
    log "TMF REST API exited with code $EXIT_CODE — restarting in 5s..."
    sleep 5
done
