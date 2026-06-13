#!/bin/bash
# Controller wrapper with automatic credential refresh.
#
# The IoT heartbeat uses Totogi-account STS credentials obtained via
# thing-login.sh (X.509 cert exchange). These expire after ~1 hour.
# The CRT library doesn't support credential_process, so we can't use
# ~/.aws/config for automatic refresh.
#
# Solution: run the controller with a credential refresh cycle.
# Every REFRESH_INTERVAL seconds, fetch fresh credentials and restart
# the controller with updated env vars. The MQTT SDK auto-reconnects
# on startup, so the heartbeat recovers within seconds.

REFRESH_INTERVAL=${CREDENTIAL_REFRESH_INTERVAL:-2700}  # 45 minutes (well before 1h expiry)

fetch_creds() {
    if [ ! -f /tmp/cert.pem ] || [ ! -f /tmp/private.key ] || [ ! -f /tmp/config.json ]; then
        echo "[controller-wrapper] No IoT credentials found, using default credentials"
        return 1
    fi

    CREDS=$(bash /usr/local/bin/thing-login.sh 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$CREDS" ]; then
        echo "[controller-wrapper] WARNING: thing-login.sh failed"
        return 1
    fi

    export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SessionToken'])")
    unset AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN

    EXPIRY=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Expiration','unknown'))")
    echo "[controller-wrapper] Credentials refreshed, expires: $EXPIRY"
    return 0
}

cd /controller

while true; do
    fetch_creds

    echo "[controller-wrapper] Starting controller (next refresh in ${REFRESH_INTERVAL}s)"
    node build/index.js &
    CONTROLLER_PID=$!

    sleep "$REFRESH_INTERVAL"

    echo "[controller-wrapper] Refreshing credentials, restarting controller"
    kill "$CONTROLLER_PID" 2>/dev/null
    wait "$CONTROLLER_PID" 2>/dev/null
done
