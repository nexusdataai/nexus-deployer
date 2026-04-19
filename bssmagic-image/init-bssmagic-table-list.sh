#!/bin/bash
# ============================================================
# init-bssmagic-table-list.sh
# Runs at container startup (background) after the base image's
# load_services.sh creates the foreign server + user mapping.
#
# In Phase 2 (Axway proxy mode), this script also overrides
# credentials from the Salesforce sandbox to Axway UAT values
# using environment variables set in the ECS task definition.
#
# Responsibilities:
#   1. Fix the user mapping login_server
#   2. Override credentials for Axway proxy mode (if env vars set)
#   3. Add credentials to the foreign server options
#   4. Create the _bssmagic_table_list foreign table
# ============================================================

MAX_WAIT=180  # seconds
WAITED=0

# --- Axway credentials from environment (set by deploy-proxy.sh) ---
# If AXWAY_TOKEN_URL is set, we're in Phase 2 (proxy mode).
# Otherwise, fall back to Phase 1 (direct Salesforce sandbox).
if [ -n "$AXWAY_TOKEN_URL" ]; then
  LOGIN_SERVER="$AXWAY_TOKEN_URL"
  OVERRIDE_CLIENT_ID="$AXWAY_CLIENT_ID"
  OVERRIDE_CLIENT_SECRET="$AXWAY_CLIENT_SECRET"
  OVERRIDE_INSTANCE_URL="$AXWAY_QUERY_URL"
  OVERRIDE_KEY_ID="$AXWAY_KEY_ID"
  OVERRIDE_PROVIDER_ORG="$AXWAY_PROVIDER_ORG"
  echo "[init-table-list] Phase 2 (Axway proxy mode) — will override credentials"
else
  LOGIN_SERVER="${SALESFORCE_LOGIN_SERVER:-https://starhub--itxp2dev.sandbox.my.salesforce.com}"
  echo "[init-table-list] Phase 1 (direct Salesforce) — login_server=$LOGIN_SERVER"
fi

# Wait for PostgreSQL to accept connections
while ! pg_isready -U postgres -d bssmagic -q 2>/dev/null; do
  sleep 2
  WAITED=$((WAITED + 2))
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "[init-table-list] Timed out waiting for PostgreSQL"
    exit 1
  fi
done

echo "[init-table-list] PostgreSQL is ready (waited ${WAITED}s)"

# Wait for the foreign server + user mapping to be created by load_services.sh
while true; do
  SRV_COUNT=$(psql -U postgres -d bssmagic -t -A -c \
    "SELECT count(*) FROM pg_foreign_server;" 2>/dev/null)
  if [ "$SRV_COUNT" -gt 0 ] 2>/dev/null; then
    SRV_NAME=$(psql -U postgres -d bssmagic -t -A -c \
      "SELECT srvname FROM pg_foreign_server LIMIT 1;" 2>/dev/null)
    echo "[init-table-list] Foreign server found: $SRV_NAME"
    break
  fi
  sleep 3
  WAITED=$((WAITED + 3))
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "[init-table-list] Timed out waiting for foreign server"
    exit 1
  fi
done

# Wait a bit more for load_services.sh to finish creating user mappings
sleep 5

SCHEMA_NAME="$SRV_NAME"

# ----------------------------------------------------------------
# Fix 1: User mapping — login_server
# ----------------------------------------------------------------
CURRENT_LOGIN=$(psql -U postgres -d bssmagic -t -A -c \
  "SELECT (SELECT split_part(opt,'=',2) FROM unnest(umoptions) opt WHERE opt LIKE 'login_server=%')
   FROM pg_user_mapping um JOIN pg_foreign_server fs ON um.umserver = fs.oid
   WHERE fs.srvname = '$SRV_NAME';" 2>/dev/null)

if [ -n "$CURRENT_LOGIN" ] && [ "$CURRENT_LOGIN" != "$LOGIN_SERVER" ]; then
  psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (SET login_server '$LOGIN_SERVER');" 2>/dev/null
  echo "[init-table-list] Fixed user mapping login_server: $CURRENT_LOGIN -> $LOGIN_SERVER"
else
  echo "[init-table-list] User mapping login_server OK: $CURRENT_LOGIN"
fi

# ----------------------------------------------------------------
# Fix 2: Phase 2 — Override user mapping credentials for Axway
# ----------------------------------------------------------------
if [ -n "$OVERRIDE_CLIENT_ID" ]; then
  echo "[init-table-list] Overriding user mapping credentials for Axway UAT..."

  # Override client_id
  psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (SET client_id '$OVERRIDE_CLIENT_ID');" 2>/dev/null \
  || psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (ADD client_id '$OVERRIDE_CLIENT_ID');" 2>/dev/null

  # Override client_secret
  psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (SET client_secret '$OVERRIDE_CLIENT_SECRET');" 2>/dev/null \
  || psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (ADD client_secret '$OVERRIDE_CLIENT_SECRET');" 2>/dev/null

  # Add/set instance_url
  psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (SET instance_url '$OVERRIDE_INSTANCE_URL');" 2>/dev/null \
  || psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (ADD instance_url '$OVERRIDE_INSTANCE_URL');" 2>/dev/null

  # Add/set key_id
  psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (SET key_id '$OVERRIDE_KEY_ID');" 2>/dev/null \
  || psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (ADD key_id '$OVERRIDE_KEY_ID');" 2>/dev/null

  # Add/set provider_org
  psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (SET provider_org '$OVERRIDE_PROVIDER_ORG');" 2>/dev/null \
  || psql -U postgres -d bssmagic -c \
    "ALTER USER MAPPING FOR CURRENT_USER SERVER \"$SRV_NAME\" OPTIONS (ADD provider_org '$OVERRIDE_PROVIDER_ORG');" 2>/dev/null

  echo "[init-table-list] User mapping overridden for Axway (client_id=$OVERRIDE_CLIENT_ID)"
fi

# ----------------------------------------------------------------
# Fix 3: Server options (FDW reads from both server + user mapping)
# ----------------------------------------------------------------
HAS_LOGIN=$(psql -U postgres -d bssmagic -t -A -c \
  "SELECT count(*) FROM pg_foreign_server WHERE srvname='$SRV_NAME'
   AND srvoptions::text LIKE '%login_server=%';" 2>/dev/null)

if [ "$HAS_LOGIN" = "0" ] 2>/dev/null; then
  if [ -n "$OVERRIDE_CLIENT_ID" ]; then
    # Phase 2: use Axway credentials directly
    CLIENT_ID="$OVERRIDE_CLIENT_ID"
    CLIENT_SECRET="$OVERRIDE_CLIENT_SECRET"
  else
    # Phase 1: pull from user mapping (populated from SSM)
    CLIENT_ID=$(psql -U postgres -d bssmagic -t -A -c \
      "SELECT (SELECT split_part(opt,'=',2) FROM unnest(umoptions) opt WHERE opt LIKE 'client_id=%')
       FROM pg_user_mapping um JOIN pg_foreign_server fs ON um.umserver = fs.oid
       WHERE fs.srvname = '$SRV_NAME';" 2>/dev/null)
    CLIENT_SECRET=$(psql -U postgres -d bssmagic -t -A -c \
      "SELECT (SELECT split_part(opt,'=',2) FROM unnest(umoptions) opt WHERE opt LIKE 'client_secret=%')
       FROM pg_user_mapping um JOIN pg_foreign_server fs ON um.umserver = fs.oid
       WHERE fs.srvname = '$SRV_NAME';" 2>/dev/null)
  fi

  API_VERSION=$(psql -U postgres -d bssmagic -t -A -c \
    "SELECT (SELECT split_part(opt,'=',2) FROM unnest(umoptions) opt WHERE opt LIKE 'api_version=%')
     FROM pg_user_mapping um JOIN pg_foreign_server fs ON um.umserver = fs.oid
     WHERE fs.srvname = '$SRV_NAME';" 2>/dev/null)

  if [ -n "$CLIENT_ID" ] && [ -n "$CLIENT_SECRET" ]; then
    # Build the ALTER SERVER statement dynamically
    ALTER_SQL="ALTER SERVER \"$SRV_NAME\" OPTIONS (
      ADD login_server '$LOGIN_SERVER',
      ADD client_id '$CLIENT_ID',
      ADD client_secret '$CLIENT_SECRET',
      ADD api_version '${API_VERSION:-v63.0}'"

    # Phase 2: also add Axway-specific options to the server
    if [ -n "$OVERRIDE_INSTANCE_URL" ]; then
      ALTER_SQL="$ALTER_SQL,
        ADD instance_url '$OVERRIDE_INSTANCE_URL',
        ADD key_id '$OVERRIDE_KEY_ID',
        ADD provider_org '$OVERRIDE_PROVIDER_ORG'"
    fi

    ALTER_SQL="$ALTER_SQL);"

    psql -U postgres -d bssmagic -c "$ALTER_SQL" 2>/dev/null
    echo "[init-table-list] Added credentials to server options"
  else
    echo "[init-table-list] WARNING: Could not read credentials from user mapping"
  fi
else
  echo "[init-table-list] Server options already have login_server"
  # Phase 2: still need to update server options with Axway values
  if [ -n "$OVERRIDE_INSTANCE_URL" ]; then
    echo "[init-table-list] Updating existing server options for Axway..."
    psql -U postgres -d bssmagic -c \
      "ALTER SERVER \"$SRV_NAME\" OPTIONS (SET login_server '$LOGIN_SERVER');" 2>/dev/null || true
    psql -U postgres -d bssmagic -c \
      "ALTER SERVER \"$SRV_NAME\" OPTIONS (SET client_id '$OVERRIDE_CLIENT_ID');" 2>/dev/null || true
    psql -U postgres -d bssmagic -c \
      "ALTER SERVER \"$SRV_NAME\" OPTIONS (SET client_secret '$OVERRIDE_CLIENT_SECRET');" 2>/dev/null || true

    # instance_url, key_id, provider_org may not exist yet — try SET then ADD
    for OPT_NAME_VAL in "instance_url=$OVERRIDE_INSTANCE_URL" "key_id=$OVERRIDE_KEY_ID" "provider_org=$OVERRIDE_PROVIDER_ORG"; do
      OPT_NAME="${OPT_NAME_VAL%%=*}"
      OPT_VAL="${OPT_NAME_VAL#*=}"
      psql -U postgres -d bssmagic -c \
        "ALTER SERVER \"$SRV_NAME\" OPTIONS (SET $OPT_NAME '$OPT_VAL');" 2>/dev/null \
      || psql -U postgres -d bssmagic -c \
        "ALTER SERVER \"$SRV_NAME\" OPTIONS (ADD $OPT_NAME '$OPT_VAL');" 2>/dev/null
    done
    echo "[init-table-list] Server options updated for Axway"
  fi
fi

# ----------------------------------------------------------------
# Fix 4: Kill existing backends so they pick up the new options
# ----------------------------------------------------------------
psql -U postgres -d bssmagic -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid != pg_backend_pid() AND datname='bssmagic';" > /dev/null 2>&1
echo "[init-table-list] Terminated existing backends to reload options"
sleep 2

# ----------------------------------------------------------------
# Create the _bssmagic_table_list foreign table
# ----------------------------------------------------------------
psql -U postgres -d bssmagic -c "CREATE SCHEMA IF NOT EXISTS \"$SCHEMA_NAME\";" 2>/dev/null

psql -U postgres -d bssmagic -c "
CREATE FOREIGN TABLE IF NOT EXISTS \"$SCHEMA_NAME\".\"_bssmagic_table_list\" (
  name text,
  description text
) SERVER \"$SRV_NAME\" OPTIONS (obj_type '_bssmagic_table_list');
" 2>/dev/null

if [ $? -eq 0 ]; then
  echo "[init-table-list] Created _bssmagic_table_list in schema $SCHEMA_NAME"
else
  echo "[init-table-list] WARNING: Failed to create _bssmagic_table_list"
fi
