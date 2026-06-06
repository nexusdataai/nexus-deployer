#!/bin/bash

# AWS SSO Login Script
# This script authenticates with AWS using IAM Identity Center (SSO)
# All configuration can be set in .env.sso.local file

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ORIGINAL_DIR="$(pwd)"

cd "$SCRIPT_DIR"

# Check if .env.sso.local exists and source it
if [ -f .env.sso.local ]; then
    set -o allexport
    source .env.sso.local
    set +o allexport
    echo "📁 Loaded configuration from .env.sso.local"
else
    echo "⚠️  No .env.sso.local file found. Creating template..."
    cat > .env.sso.local << 'EOF'
# AWS SSO (IAM Identity Center) Configuration
# Fill in your values below

# SSO Start URL (required) - from your AWS access portal
SSO_START_URL=https://ptrtechnology.awsapps.com/start

# SSO Region (default: us-east-1)
SSO_REGION=us-east-1

# SSO Session Name (default: my-sso)
SSO_SESSION_NAME=my-sso

# SSO Registration Scopes (default: sso:account:access)
SSO_REGISTRATION_SCOPES=sso:account:access

# ── Account Definitions ─────────────────────────────────────────────
# Define your AWS accounts below. Add more by incrementing the number.

# Account 1: PTR Technologies
SSO_ACCOUNT_1_NAME="PTR Technologies"
SSO_ACCOUNT_1_ID=654654554404
SSO_ACCOUNT_1_ROLE=AdministratorAccess
SSO_ACCOUNT_1_PROFILE=ptr-tech
SSO_ACCOUNT_1_REGION=us-east-1

# Account 2: PromodeAgroFarms
SSO_ACCOUNT_2_NAME=PromodeAgroFarms
SSO_ACCOUNT_2_ID=851725323791
SSO_ACCOUNT_2_ROLE=AdministratorAccess
SSO_ACCOUNT_2_PROFILE=promode-agro
SSO_ACCOUNT_2_REGION=us-east-1

# ── Defaults ────────────────────────────────────────────────────────

# Default profile to activate after login (must match one of the SSO_ACCOUNT_*_PROFILE values above)
DEFAULT_PROFILE=ptr-tech

# Generate AWS Console signin URL after login (true/false, default: false)
# PRINT_CONSOLE_URL=false
EOF
    echo "✅ Created template .env.sso.local file"
    echo "📝 Please review .env.sso.local and run this script again"
    cd "$ORIGINAL_DIR"
    exit 0
fi

# Set defaults for optional variables
: "${SSO_START_URL:=https://ptrtechnology.awsapps.com/start}"
: "${SSO_REGION:=us-east-1}"
: "${SSO_SESSION_NAME:=my-sso}"
: "${SSO_REGISTRATION_SCOPES:=sso:account:access}"
: "${DEFAULT_PROFILE:=ptr-tech}"
: "${PRINT_CONSOLE_URL:=false}"

# Collect all defined accounts into arrays
ACCOUNT_NAMES=()
ACCOUNT_IDS=()
ACCOUNT_ROLES=()
ACCOUNT_PROFILES=()
ACCOUNT_REGIONS=()

i=1
while true; do
    eval "acc_id=\${SSO_ACCOUNT_${i}_ID}"
    [ -z "$acc_id" ] && break
    eval "acc_name=\${SSO_ACCOUNT_${i}_NAME:-Account $i}"
    eval "acc_role=\${SSO_ACCOUNT_${i}_ROLE:-AdministratorAccess}"
    eval "acc_profile=\${SSO_ACCOUNT_${i}_PROFILE:-sso-account-$i}"
    eval "acc_region=\${SSO_ACCOUNT_${i}_REGION:-$SSO_REGION}"
    ACCOUNT_NAMES+=("$acc_name")
    ACCOUNT_IDS+=("$acc_id")
    ACCOUNT_ROLES+=("$acc_role")
    ACCOUNT_PROFILES+=("$acc_profile")
    ACCOUNT_REGIONS+=("$acc_region")
    i=$((i + 1))
done

ACTIVE_PROFILE="$DEFAULT_PROFILE"
FORCE_LOGIN=false
SHOW_LIST=false
SHOW_STATUS=false

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --profile) ACTIVE_PROFILE="$2"; shift ;;
        --list) SHOW_LIST=true ;;
        --login) FORCE_LOGIN=true ;;
        --status) SHOW_STATUS=true ;;
        --console-url) PRINT_CONSOLE_URL=true ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "AWS SSO Login - authenticate via IAM Identity Center (browser-based)"
            echo ""
            echo "Options:"
            echo "  --profile PROFILE   Activate a specific profile after login (default: $DEFAULT_PROFILE)"
            echo "  --list              List all configured SSO profiles"
            echo "  --login             Force re-login even if session is still valid"
            echo "  --status            Check current SSO session and credential status"
            echo "  --console-url       Generate AWS Console sign-in URL after login"
            echo "  --help              Show this help message"
            echo ""
            echo "Configured accounts:"
            for idx in "${!ACCOUNT_IDS[@]}"; do
                echo "  ${ACCOUNT_NAMES[$idx]} (${ACCOUNT_IDS[$idx]}) -> profile: ${ACCOUNT_PROFILES[$idx]}"
            done
            echo ""
            echo "All settings can be configured in .env.sso.local file"
            cd "$ORIGINAL_DIR"
            exit 0
            ;;
        *) echo "Unknown parameter: $1"; cd "$ORIGINAL_DIR"; exit 1 ;;
    esac
    shift
done

if [ ${#ACCOUNT_IDS[@]} -eq 0 ]; then
    echo "❌ No accounts configured in .env.sso.local"
    echo "   Add at least one SSO_ACCOUNT_1_ID entry"
    cd "$ORIGINAL_DIR"
    exit 1
fi

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI v2 first."
    echo "   https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    cd "$ORIGINAL_DIR"
    exit 1
fi

# ── --list: show configured profiles and exit ───────────────────────
if [ "$SHOW_LIST" = "true" ]; then
    echo ""
    echo "📋 Configured SSO Profiles:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    for idx in "${!ACCOUNT_IDS[@]}"; do
        marker=""
        [ "${ACCOUNT_PROFILES[$idx]}" = "$ACTIVE_PROFILE" ] && marker=" ← active"
        printf "  %-20s %-14s %-22s %s\n" \
            "${ACCOUNT_NAMES[$idx]}" "${ACCOUNT_IDS[$idx]}" "profile: ${ACCOUNT_PROFILES[$idx]}" "$marker"
    done
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "SSO Session: $SSO_SESSION_NAME"
    echo "Start URL:   $SSO_START_URL"
    cd "$ORIGINAL_DIR"
    exit 0
fi

# ── Ensure ~/.aws/config has the SSO session and all profile entries ─
mkdir -p ~/.aws
touch ~/.aws/config

if ! grep -q "\[sso-session $SSO_SESSION_NAME\]" ~/.aws/config 2>/dev/null; then
    echo "📝 Adding SSO session '$SSO_SESSION_NAME' to ~/.aws/config"
    cat >> ~/.aws/config << EOF

[sso-session $SSO_SESSION_NAME]
sso_start_url = $SSO_START_URL
sso_region = $SSO_REGION
sso_registration_scopes = $SSO_REGISTRATION_SCOPES
EOF
fi

for idx in "${!ACCOUNT_IDS[@]}"; do
    prof="${ACCOUNT_PROFILES[$idx]}"
    if ! grep -q "\[profile $prof\]" ~/.aws/config 2>/dev/null; then
        echo "📝 Adding profile '$prof' to ~/.aws/config"
        cat >> ~/.aws/config << EOF

[profile $prof]
sso_session = $SSO_SESSION_NAME
sso_account_id = ${ACCOUNT_IDS[$idx]}
sso_role_name = ${ACCOUNT_ROLES[$idx]}
region = ${ACCOUNT_REGIONS[$idx]}
output = json
EOF
    fi
done

# ── Helper: check if SSO session token is still valid ────────────────
sso_session_valid() {
    local cache_dir="$HOME/.aws/sso/cache"
    [ ! -d "$cache_dir" ] && return 1

    for f in "$cache_dir"/*.json; do
        [ ! -f "$f" ] && continue
        if grep -q "startUrl" "$f" 2>/dev/null; then
            local expires_at
            expires_at=$(python3 -c "
import json, sys, datetime
with open('$f') as fh:
    data = json.load(fh)
exp = data.get('expiresAt', '')
if not exp:
    sys.exit(1)
exp = exp.replace('UTC', '+00:00')
try:
    dt = datetime.datetime.fromisoformat(exp)
except:
    dt = datetime.datetime.strptime(exp, '%Y-%m-%dT%H:%M:%S%z')
now = datetime.datetime.now(datetime.timezone.utc)
sys.exit(0 if dt > now else 1)
" 2>/dev/null)
            if [ $? -eq 0 ]; then
                return 0
            fi
        fi
    done
    return 1
}

# ── --status: show session & credential status and exit ──────────────
if [ "$SHOW_STATUS" = "true" ]; then
    echo ""
    echo "📊 SSO Session Status"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "   Session:   $SSO_SESSION_NAME"
    echo "   Start URL: $SSO_START_URL"
    if sso_session_valid; then
        echo "   Status:    ✅ Active"
    else
        echo "   Status:    ❌ Expired or not logged in"
    fi
    echo ""
    echo "📋 Profile Credentials:"
    for idx in "${!ACCOUNT_IDS[@]}"; do
        prof="${ACCOUNT_PROFILES[$idx]}"
        printf "   %-20s (%s) " "${ACCOUNT_NAMES[$idx]}" "$prof"
        if aws sts get-caller-identity --profile "$prof" &>/dev/null; then
            echo "✅"
        else
            echo "❌"
        fi
    done
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cd "$ORIGINAL_DIR"
    exit 0
fi

# ── Validate the chosen profile exists in our config ─────────────────
PROFILE_VALID=false
PROFILE_IDX=0
for idx in "${!ACCOUNT_PROFILES[@]}"; do
    if [ "${ACCOUNT_PROFILES[$idx]}" = "$ACTIVE_PROFILE" ]; then
        PROFILE_VALID=true
        PROFILE_IDX=$idx
        break
    fi
done

if [ "$PROFILE_VALID" = "false" ]; then
    echo "❌ Profile '$ACTIVE_PROFILE' not found in configured accounts."
    echo "   Available profiles:"
    for idx in "${!ACCOUNT_PROFILES[@]}"; do
        echo "     ${ACCOUNT_PROFILES[$idx]}  (${ACCOUNT_NAMES[$idx]} - ${ACCOUNT_IDS[$idx]})"
    done
    cd "$ORIGINAL_DIR"
    exit 1
fi

echo ""
echo "🔐 Logging in to AWS via SSO (IAM Identity Center)..."
echo "   Current Dir:  $ORIGINAL_DIR"
echo "   Script Dir:   $SCRIPT_DIR"
echo "   SSO Start URL: $SSO_START_URL"
echo "   SSO Session:  $SSO_SESSION_NAME"
echo "   Active Profile: $ACTIVE_PROFILE"
echo "   Account:      ${ACCOUNT_NAMES[$PROFILE_IDX]} (${ACCOUNT_IDS[$PROFILE_IDX]})"
echo "   Role:         ${ACCOUNT_ROLES[$PROFILE_IDX]}"
echo "   Region:       ${ACCOUNT_REGIONS[$PROFILE_IDX]}"
echo ""

# ── SSO Login ────────────────────────────────────────────────────────
NEED_LOGIN=true

if [ "$FORCE_LOGIN" = "false" ] && sso_session_valid; then
    echo "✅ SSO session is still valid. Skipping browser login."
    echo "   (Use --login to force re-authentication)"
    NEED_LOGIN=false
fi

if [ "$NEED_LOGIN" = "true" ]; then
    echo "🌐 Opening browser for SSO authentication..."
    echo "   If the browser does not open automatically, check the terminal for a URL to visit."
    echo ""
    aws sso login --sso-session "$SSO_SESSION_NAME"
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo "❌ SSO login failed."
        echo "📍 Returning to: $ORIGINAL_DIR"
        cd "$ORIGINAL_DIR"
        exit $EXIT_CODE
    fi
    echo ""
    echo "✅ SSO authentication successful!"
fi

# ── Verify credentials for the active profile ────────────────────────
echo ""
echo "🔍 Verifying credentials for profile: $ACTIVE_PROFILE ..."
IDENTITY_OUTPUT=$(aws sts get-caller-identity --profile "$ACTIVE_PROFILE" 2>&1)
VERIFY_CODE=$?

if [ $VERIFY_CODE -ne 0 ]; then
    echo "❌ Credential verification failed for profile '$ACTIVE_PROFILE'"
    echo "   $IDENTITY_OUTPUT"
    echo ""
    echo "   This may happen if:"
    echo "   - The SSO session expired between login and verification"
    echo "   - The account/role configuration is incorrect in .env.sso.local"
    echo "   Try: $0 --login"
    echo "📍 Returning to: $ORIGINAL_DIR"
    cd "$ORIGINAL_DIR"
    exit 1
fi

CALLER_ACCOUNT=$(echo "$IDENTITY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Account',''))" 2>/dev/null)
CALLER_ARN=$(echo "$IDENTITY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Arn',''))" 2>/dev/null)
CALLER_USER_ID=$(echo "$IDENTITY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('UserId',''))" 2>/dev/null)

echo "✅ Credentials verified!"
echo "   Account: $CALLER_ACCOUNT"
echo "   ARN:     $CALLER_ARN"
echo "   UserId:  $CALLER_USER_ID"

# ── Console URL Generation ───────────────────────────────────────────
if [ "$PRINT_CONSOLE_URL" = "true" ]; then
    echo ""
    echo "🌐 Generating AWS Console sign-in URL..."

    ROLE_CREDS=$(aws sso get-role-credentials \
        --account-id "${ACCOUNT_IDS[$PROFILE_IDX]}" \
        --role-name "${ACCOUNT_ROLES[$PROFILE_IDX]}" \
        --access-token "$(python3 -c "
import json, glob, os
cache_dir = os.path.expanduser('~/.aws/sso/cache')
for f in sorted(glob.glob(os.path.join(cache_dir, '*.json')), key=os.path.getmtime, reverse=True):
    with open(f) as fh:
        data = json.load(fh)
    if 'accessToken' in data:
        print(data['accessToken'])
        break
" 2>/dev/null)" \
        --region "$SSO_REGION" 2>&1)

    RC_EXIT=$?
    if [ $RC_EXIT -ne 0 ]; then
        echo "⚠️  Could not retrieve role credentials for console URL generation."
        echo "   $ROLE_CREDS"
    else
        ACCESS_KEY=$(echo "$ROLE_CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['roleCredentials']['accessKeyId'])" 2>/dev/null)
        SECRET_KEY=$(echo "$ROLE_CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['roleCredentials']['secretAccessKey'])" 2>/dev/null)
        SESSION_TOKEN=$(echo "$ROLE_CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['roleCredentials']['sessionToken'])" 2>/dev/null)

        if [ -n "$ACCESS_KEY" ] && [ -n "$SECRET_KEY" ] && [ -n "$SESSION_TOKEN" ]; then
            CONSOLE_URL=$(python3 -c "
import json, urllib.request, urllib.parse

creds = json.dumps({
    'sessionId': '$ACCESS_KEY',
    'sessionKey': '$SECRET_KEY',
    'sessionToken': '$SESSION_TOKEN'
})

signin_url = 'https://signin.aws.amazon.com/federation'
get_token_url = signin_url + '?' + urllib.parse.urlencode({
    'Action': 'getSigninToken',
    'SessionDuration': '3600',
    'Session': creds
})

try:
    resp = urllib.request.urlopen(get_token_url)
    token = json.loads(resp.read().decode())['SigninToken']
    login_url = signin_url + '?' + urllib.parse.urlencode({
        'Action': 'login',
        'Issuer': '',
        'Destination': 'https://console.aws.amazon.com/',
        'SigninToken': token
    })
    print(login_url)
except Exception as e:
    import sys
    print('ERROR: ' + str(e), file=sys.stderr)
" 2>/dev/null)

            if [ -n "$CONSOLE_URL" ]; then
                echo ""
                echo "🌐 AWS Management Console Sign-in URL:"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "$CONSOLE_URL"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo ""
                echo "💡 TIP: Copy and paste this URL into your browser to access the AWS Console"
                echo "⏱️  This URL is valid for 1 hour"
                echo ""
                echo "⚠️  BROWSER SESSION NOTE:"
                echo "   If the console shows a different account than expected:"
                echo "   1. Sign out from AWS Console first (top-right menu → Sign Out)"
                echo "   2. Use an Incognito/Private browser window, OR"
                echo "   3. Clear your browser's AWS cookies before using the URL"
            else
                echo "⚠️  Console URL generation failed."
            fi
        else
            echo "⚠️  Could not parse role credentials for console URL."
        fi
    fi
fi

# ── Success summary ──────────────────────────────────────────────────
echo ""
echo "✅ Login successful! Active profile: $ACTIVE_PROFILE"
echo ""

echo "🎯 To use these credentials:"
echo ""
echo "Option 1: Set environment variable (recommended for this session):"
echo "   export AWS_PROFILE=$ACTIVE_PROFILE"
echo "   aws s3 ls"
echo ""
echo "Option 2: Specify profile in each command:"
echo "   aws s3 ls --profile $ACTIVE_PROFILE"
echo ""

if [ ${#ACCOUNT_IDS[@]} -gt 1 ]; then
    echo "🔄 Switch accounts (no re-login needed):"
    for idx in "${!ACCOUNT_PROFILES[@]}"; do
        if [ "${ACCOUNT_PROFILES[$idx]}" != "$ACTIVE_PROFILE" ]; then
            echo "   export AWS_PROFILE=${ACCOUNT_PROFILES[$idx]}   # ${ACCOUNT_NAMES[$idx]} (${ACCOUNT_IDS[$idx]})"
        fi
    done
    echo ""
fi

echo "Test your credentials:"
echo "   aws sts get-caller-identity --profile $ACTIVE_PROFILE"
echo ""
echo "📍 Returning to: $ORIGINAL_DIR"

cd "$ORIGINAL_DIR"
echo "✅ Done! You're back in: $(pwd)"
