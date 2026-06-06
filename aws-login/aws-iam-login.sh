#!/bin/bash

# AWS IAM Login Script
# Sets up AWS CLI profiles from long-term IAM-user credentials stored in
# .env.iam.local. Standalone-account / non-federated counterpart to
# aws-sso-login.sh (which is for IAM Identity Center / SSO accounts) and
# aws-login.sh (which is for ADFS-federated accounts).
#
# Use this for accounts that are NOT members of your AWS Organization
# (and therefore not visible in your IAM Identity Center portal) and
# NOT federated via ADFS. Typically standalone accounts where you've
# already created an IAM user with long-term programmatic access (e.g.
# via aws-iam-bootstrap.sh).
#
# Different from aws-iam-bootstrap.sh:
#   - bootstrap creates the IAM user + keys (run once per account, with root keys)
#   - login just configures the local CLI profile from existing keys
#     (run on any machine, with the IAM user's keys)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ORIGINAL_DIR="$(pwd)"

cd "$SCRIPT_DIR"

# Check if .env.iam.local exists and source it
if [ -f .env.iam.local ]; then
    set -o allexport
    # shellcheck disable=SC1091
    source .env.iam.local
    set +o allexport
    echo "📁 Loaded configuration from .env.iam.local"
else
    echo "⚠️  No .env.iam.local file found. Creating template..."
    cat > .env.iam.local << 'EOF'
# AWS IAM Long-term Credentials Configuration
# Used by aws-iam-login.sh to set up local CLI profiles for accounts
# that are NOT in your AWS Organization (so not reachable via SSO).
#
# Security:
#   - chmod 600 this file before populating it
#   - DO NOT commit it to git (.gitignore should exclude .env.*.local)
#   - Rotate IAM user keys every ~90 days

# ── Account Definitions ─────────────────────────────────────────────
# Define accounts below. Add more by incrementing the number.

# Account 1
IAM_ACCOUNT_1_NAME="Promode-Agro-Official"
IAM_ACCOUNT_1_ID=040740747817
IAM_ACCOUNT_1_PROFILE=promode-official
IAM_ACCOUNT_1_REGION=us-east-1
IAM_ACCOUNT_1_ACCESS_KEY_ID=
IAM_ACCOUNT_1_SECRET_ACCESS_KEY=
# IAM_ACCOUNT_1_SESSION_TOKEN=    # only if using STS temporary credentials

# Add more accounts by incrementing:
# IAM_ACCOUNT_2_NAME=
# IAM_ACCOUNT_2_ID=
# IAM_ACCOUNT_2_PROFILE=
# IAM_ACCOUNT_2_REGION=us-east-1
# IAM_ACCOUNT_2_ACCESS_KEY_ID=
# IAM_ACCOUNT_2_SECRET_ACCESS_KEY=

# ── Defaults ────────────────────────────────────────────────────────

# Default profile to activate after login (must match an IAM_ACCOUNT_*_PROFILE above)
DEFAULT_PROFILE=promode-official
EOF
    chmod 600 .env.iam.local 2>/dev/null || true
    echo "✅ Created template .env.iam.local file"
    echo "📝 Please populate IAM_ACCOUNT_*_ACCESS_KEY_ID / SECRET_ACCESS_KEY and run again"
    cd "$ORIGINAL_DIR"
    exit 0
fi

# Permission warning - this file holds long-term IAM user credentials
PERMS=$(stat -c '%a' .env.iam.local 2>/dev/null || echo "")
if [[ -n "$PERMS" && "$PERMS" != "600" && "$PERMS" != "400" ]]; then
    echo "⚠️  .env.iam.local permissions are $PERMS; expected 600. Run: chmod 600 $SCRIPT_DIR/.env.iam.local"
fi

# Set defaults for optional variables
: "${DEFAULT_PROFILE:=}"
: "${PRINT_CONSOLE_URL:=false}"

# Collect all defined accounts into arrays (matching aws-sso-login.sh pattern)
ACCOUNT_NAMES=()
ACCOUNT_IDS=()
ACCOUNT_PROFILES=()
ACCOUNT_REGIONS=()
ACCOUNT_AKS=()
ACCOUNT_SKS=()
ACCOUNT_TOKENS=()

i=1
while true; do
    eval "acc_id=\${IAM_ACCOUNT_${i}_ID:-}"
    eval "acc_ak=\${IAM_ACCOUNT_${i}_ACCESS_KEY_ID:-}"
    eval "acc_sk=\${IAM_ACCOUNT_${i}_SECRET_ACCESS_KEY:-}"
    # An account entry is "present" only if at least an ID OR an access key is set
    if [ -z "$acc_id" ] && [ -z "$acc_ak" ]; then
        break
    fi
    eval "acc_name=\${IAM_ACCOUNT_${i}_NAME:-Account $i}"
    eval "acc_profile=\${IAM_ACCOUNT_${i}_PROFILE:-iam-account-$i}"
    eval "acc_region=\${IAM_ACCOUNT_${i}_REGION:-us-east-1}"
    eval "acc_token=\${IAM_ACCOUNT_${i}_SESSION_TOKEN:-}"
    ACCOUNT_NAMES+=("$acc_name")
    ACCOUNT_IDS+=("$acc_id")
    ACCOUNT_PROFILES+=("$acc_profile")
    ACCOUNT_REGIONS+=("$acc_region")
    ACCOUNT_AKS+=("$acc_ak")
    ACCOUNT_SKS+=("$acc_sk")
    ACCOUNT_TOKENS+=("$acc_token")
    i=$((i + 1))
done

# Fallback: simple flat format. If no IAM_ACCOUNT_N_* entries were found but
# the file has bare AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_PROFILE
# variables, treat them as a single account.
if [ ${#ACCOUNT_IDS[@]} -eq 0 ] && [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    simple_profile="${AWS_PROFILE:-default}"
    simple_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
    ACCOUNT_NAMES+=("$simple_profile")
    ACCOUNT_IDS+=("")
    ACCOUNT_PROFILES+=("$simple_profile")
    ACCOUNT_REGIONS+=("$simple_region")
    ACCOUNT_AKS+=("$AWS_ACCESS_KEY_ID")
    ACCOUNT_SKS+=("$AWS_SECRET_ACCESS_KEY")
    ACCOUNT_TOKENS+=("${AWS_SESSION_TOKEN:-}")
    if [ -z "$DEFAULT_PROFILE" ]; then
        DEFAULT_PROFILE="$simple_profile"
    fi
fi

ACTIVE_PROFILE="$DEFAULT_PROFILE"
SHOW_LIST=false
SHOW_STATUS=false

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --profile) ACTIVE_PROFILE="$2"; shift ;;
        --list)    SHOW_LIST=true ;;
        --status)  SHOW_STATUS=true ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "AWS IAM Login - configure CLI profiles from long-term IAM-user keys"
            echo ""
            echo "Options:"
            echo "  --profile PROFILE   Activate a specific profile (default: $DEFAULT_PROFILE)"
            echo "  --list              List all configured IAM profiles"
            echo "  --status            Verify each profile by calling sts get-caller-identity"
            echo "  --help              Show this help message"
            echo ""
            echo "Configured accounts:"
            for idx in "${!ACCOUNT_IDS[@]}"; do
                echo "  ${ACCOUNT_NAMES[$idx]} (${ACCOUNT_IDS[$idx]}) -> profile: ${ACCOUNT_PROFILES[$idx]}"
            done
            echo ""
            echo "All settings can be configured in .env.iam.local"
            cd "$ORIGINAL_DIR"
            exit 0
            ;;
        *) echo "Unknown parameter: $1"; cd "$ORIGINAL_DIR"; exit 1 ;;
    esac
    shift
done

if [ ${#ACCOUNT_IDS[@]} -eq 0 ]; then
    echo "❌ No accounts configured in .env.iam.local"
    echo "   Add at least one IAM_ACCOUNT_1_ID + IAM_ACCOUNT_1_ACCESS_KEY_ID + IAM_ACCOUNT_1_SECRET_ACCESS_KEY"
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
    echo "📋 Configured IAM Profiles:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    for idx in "${!ACCOUNT_IDS[@]}"; do
        marker=""
        [ "${ACCOUNT_PROFILES[$idx]}" = "$ACTIVE_PROFILE" ] && marker=" ← active"
        printf "  %-24s %-14s %-22s %s\n" \
            "${ACCOUNT_NAMES[$idx]}" "${ACCOUNT_IDS[$idx]}" "profile: ${ACCOUNT_PROFILES[$idx]}" "$marker"
    done
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cd "$ORIGINAL_DIR"
    exit 0
fi

# ── --status: verify each profile against AWS and exit ──────────────
if [ "$SHOW_STATUS" = "true" ]; then
    echo ""
    echo "📊 IAM Profile Status"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    # Scrub any inherited AWS_* env vars so the profile is what's tested.
    unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_SESSION_TOKEN AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
    for idx in "${!ACCOUNT_IDS[@]}"; do
        prof="${ACCOUNT_PROFILES[$idx]}"
        printf "   %-24s (%s) " "${ACCOUNT_NAMES[$idx]}" "$prof"
        if AWS_PAGER="" aws --profile "$prof" --no-cli-pager sts get-caller-identity \
            --query 'Account' --output text >/dev/null 2>&1; then
            echo "✅"
        else
            echo "❌  (not configured, expired, or keys invalid)"
        fi
    done
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cd "$ORIGINAL_DIR"
    exit 0
fi

# ── Validate the chosen profile exists in our config ────────────────
if [ -z "$ACTIVE_PROFILE" ]; then
    # No --profile passed and no DEFAULT_PROFILE set; pick the first
    ACTIVE_PROFILE="${ACCOUNT_PROFILES[0]}"
fi

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

# Pull the chosen account's fields
ACC_NAME="${ACCOUNT_NAMES[$PROFILE_IDX]}"
ACC_ID="${ACCOUNT_IDS[$PROFILE_IDX]}"
ACC_PROFILE="${ACCOUNT_PROFILES[$PROFILE_IDX]}"
ACC_REGION="${ACCOUNT_REGIONS[$PROFILE_IDX]}"
ACC_AK="${ACCOUNT_AKS[$PROFILE_IDX]}"
ACC_SK="${ACCOUNT_SKS[$PROFILE_IDX]}"
ACC_TOKEN="${ACCOUNT_TOKENS[$PROFILE_IDX]}"

# Length sanity checks (real AWS keys are 20 chars; secrets 40 chars)
if [ -z "$ACC_AK" ] || [ ${#ACC_AK} -lt 16 ]; then
    echo "❌ IAM_ACCOUNT_${PROFILE_IDX_PLUS:-$((PROFILE_IDX + 1))}_ACCESS_KEY_ID is missing or suspiciously short (${#ACC_AK} chars; expected ~20)"
    echo "   Edit .env.iam.local and set the access key for '$ACC_PROFILE'."
    cd "$ORIGINAL_DIR"
    exit 1
fi
if [ -z "$ACC_SK" ] || [ ${#ACC_SK} -lt 30 ]; then
    echo "❌ IAM_ACCOUNT_$((PROFILE_IDX + 1))_SECRET_ACCESS_KEY is missing or suspiciously short (${#ACC_SK} chars; expected ~40)"
    echo "   Edit .env.iam.local and set the secret key for '$ACC_PROFILE'."
    cd "$ORIGINAL_DIR"
    exit 1
fi

echo ""
echo "🔐 Configuring AWS profile from IAM user credentials..."
echo "   Current Dir:    $ORIGINAL_DIR"
echo "   Script Dir:     $SCRIPT_DIR"
echo "   Active Profile: $ACC_PROFILE"
echo "   Account:        $ACC_NAME ($ACC_ID)"
echo "   Region:         $ACC_REGION"
echo "   Access Key:     ${ACC_AK:0:4}**** (${#ACC_AK} chars, ${#ACC_SK}-char secret)"
[ -n "$ACC_TOKEN" ] && echo "   Session Token:  present (${#ACC_TOKEN} chars)"
echo ""

# ── Backup existing credentials if profile already present ──────────
CREDS_FILE="${HOME}/.aws/credentials"
mkdir -p "$(dirname "$CREDS_FILE")"
if [ -f "$CREDS_FILE" ] && grep -q "^\[${ACC_PROFILE}\]$" "$CREDS_FILE"; then
    BACKUP="${CREDS_FILE}.bak.$(date +%Y%m%dT%H%M%SZ)"
    cp "$CREDS_FILE" "$BACKUP"
    echo "💾 Existing profile detected; backed up credentials file to $BACKUP"
fi

# ── Write the profile via `aws configure set` ───────────────────────
echo "📝 Writing profile '$ACC_PROFILE' to ~/.aws/credentials and ~/.aws/config..."
aws configure set aws_access_key_id     "$ACC_AK"     --profile "$ACC_PROFILE"
aws configure set aws_secret_access_key "$ACC_SK"     --profile "$ACC_PROFILE"
aws configure set region                "$ACC_REGION" --profile "$ACC_PROFILE"
aws configure set output                json          --profile "$ACC_PROFILE"
if [ -n "$ACC_TOKEN" ]; then
    aws configure set aws_session_token "$ACC_TOKEN" --profile "$ACC_PROFILE"
fi
echo "   ✅ Profile written"
echo ""

# ── Verify the profile resolves correctly ───────────────────────────
echo "🔍 Verifying profile '$ACC_PROFILE' against AWS..."
# Scrub any inherited AWS_* env vars so the profile is what's tested.
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_SESSION_TOKEN AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

# IAM keys can take a few seconds to propagate if freshly created.
VERIFIED_ACCOUNT=""
VERIFIED_ARN=""
attempts=0
while [ $attempts -lt 6 ]; do
    out=$(AWS_PAGER="" aws --profile "$ACC_PROFILE" --region "$ACC_REGION" \
        --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 20 \
        sts get-caller-identity --output json 2>/dev/null || echo "")
    if [ -n "$out" ]; then
        VERIFIED_ACCOUNT=$(echo "$out" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Account',''))" 2>/dev/null || echo "")
        VERIFIED_ARN=$(echo "$out" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Arn',''))" 2>/dev/null || echo "")
        if [ -n "$VERIFIED_ACCOUNT" ]; then
            break
        fi
    fi
    attempts=$((attempts + 1))
    sleep 5
done

if [ -z "$VERIFIED_ACCOUNT" ]; then
    echo "❌ Profile verification failed - sts get-caller-identity returned no account."
    echo "   The keys in .env.iam.local may be invalid, revoked, or for a different account."
    echo "   Test directly:"
    echo "     aws --profile $ACC_PROFILE sts get-caller-identity"
    cd "$ORIGINAL_DIR"
    exit 1
fi

if [ -n "$ACC_ID" ] && [ "$VERIFIED_ACCOUNT" != "$ACC_ID" ]; then
    echo "⚠️  Verified account ($VERIFIED_ACCOUNT) does not match configured ID ($ACC_ID)."
    echo "   Profile is set up but IAM_ACCOUNT_$((PROFILE_IDX + 1))_ID in .env.iam.local is wrong."
fi

echo "   ✅ Verified: account $VERIFIED_ACCOUNT, arn=$VERIFIED_ARN"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 Login complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Profile:  $ACC_PROFILE"
echo "   Account:  $VERIFIED_ACCOUNT ($ACC_NAME)"
echo "   Region:   $ACC_REGION"
echo ""
echo "Use with any AWS tool:"
echo "   AWS_PROFILE=$ACC_PROFILE <command>"
echo "   aws --profile $ACC_PROFILE <command>"
echo ""
echo "Or activate the profile in the current shell:"
echo "   export AWS_PROFILE=$ACC_PROFILE"
echo ""

cd "$ORIGINAL_DIR"
