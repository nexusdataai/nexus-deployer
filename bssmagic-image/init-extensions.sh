#!/bin/bash
# ============================================================
# init-extensions.sh
# ============================================================
# Configures PostgreSQL extensions required by the AI Control
# Plane. The extension PACKAGES (pgvector, Apache AGE) are
# installed at Docker build time in the Dockerfile. This script
# only handles runtime SQL: creating extensions, tables, and
# the AGE graph — which require a running PostgreSQL instance.
#
# Runs after restore-if-needed.sh (waits for foreign tables).
# ============================================================

set +e

DB_NAME="${POSTGRES_DB:-bssmagic}"
DB_USER="${POSTGRES_USER:-postgres}"
MAX_WAIT=180
WAITED=0

log() { echo "[extensions] $*"; }

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

# --- Wait for restore to finish (foreign tables > 10) ---
log "Waiting for DB restore to complete..."
while true; do
  FT_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
    "SELECT count(*) FROM pg_foreign_table;" 2>/dev/null || echo "0")
  if [ "$FT_COUNT" -gt 10 ] 2>/dev/null; then
    log "DB restore complete ($FT_COUNT foreign tables)"
    break
  fi
  sleep 5
  WAITED=$((WAITED + 5))
  if [ $WAITED -ge $MAX_WAIT ]; then
    log "WARN: Timed out waiting for restore — proceeding anyway"
    break
  fi
done

# =============================================================
# 1. pgvector — enable extension + create embeddings table
# =============================================================
log "Enabling pgvector extension..."
psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null \
  && log "pgvector extension enabled" \
  || log "WARN: pgvector extension creation failed"

psql -U "$DB_USER" -d "$DB_NAME" <<'EOSQL'
CREATE TABLE IF NOT EXISTS control_plane_embeddings (
    id SERIAL PRIMARY KEY,
    content_type VARCHAR(50) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_cpe_content_type ON control_plane_embeddings(content_type);
EOSQL
log "control_plane_embeddings table ready"

# =============================================================
# 2. Apache AGE — enable extension + create graph
# =============================================================
AGE_INSTALLED=$(psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT count(*) FROM pg_available_extensions WHERE name = 'age';" 2>/dev/null || echo "0")

if [ "$AGE_INSTALLED" -gt 0 ] 2>/dev/null; then
  psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS age;" 2>/dev/null
  psql -U "$DB_USER" -d "$DB_NAME" -c "LOAD 'age'; SET search_path = ag_catalog, public; SELECT create_graph('enterprise_onto');" 2>/dev/null || true
  log "Apache AGE extension and enterprise_onto graph ready"
else
  log "Apache AGE not available — graph queries will use metadata fallback via pgvector"
fi

# =============================================================
# 3. Mapping rules table (for VirtualQueryService)
# =============================================================
psql -U "$DB_USER" -d "$DB_NAME" <<'EOSQL'
CREATE TABLE IF NOT EXISTS mapping_rules (
    id VARCHAR(255) PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
EOSQL
log "mapping_rules table ready"

log "Extension setup complete"
