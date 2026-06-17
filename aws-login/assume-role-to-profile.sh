#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ENV_FILE="$SCRIPT_DIR/.env.roles.local"

usage() {
  echo "Usage:"
  echo "  $0 --<profile-name> [--source-profile NAME] [--console-url] [--duration N] [--region R] [--external-id ID]"
  echo "  $0 <role-arn> <profile-name> [--source-profile NAME] [--console-url] [--duration N] [--region R] [--external-id ID]"
  echo ""
  echo "Options:"
  echo "  --source-profile NAME  Base AWS profile used to call sts:AssumeRole (default: \$AWS_SOURCE_PROFILE or ptr-tech)"
  echo "                         Must have valid credentials — log in first with aws-sso-login.sh --profile NAME"
  echo "  --no-console-url Suppress the AWS Console sign-in URL (printed by default)"
  echo "  --duration N     STS session duration in seconds (default: 3600, role MaxSessionDuration permitting)"
  echo "  --region R       Region for the console destination URL (default: \$AWS_REGION or us-east-1)"
  echo "  --external-id ID Pass sts:ExternalId on the assume-role call (overrides any value in the env file)"
  echo ""
  echo "Env file format ($ENV_FILE):"
  echo "  <profile>=<role-arn>                    # no ExternalId"
  echo "  <profile>=<role-arn>|<external-id>      # require this ExternalId on assume"
  if [ -f "$ENV_FILE" ]; then
    local profiles
    profiles=$(grep -E '^[[:space:]]*[A-Za-z0-9_.-]+[[:space:]]*=' "$ENV_FILE" 2>/dev/null \
      | sed -E 's/^[[:space:]]*//; s/[[:space:]]*=.*//')
    if [ -n "$profiles" ]; then
      echo ""
      echo "Available profiles in $ENV_FILE:"
      echo "$profiles" | sed 's/^/  --/'
    fi
  fi
}

ROLE_ARN=""
PROFILE_NAME=""
PROFILE_EXTERNAL_ID=""    # from env file (key=arn|external-id)
EXTERNAL_ID_CLI=""        # from --external-id flag
PRINT_CONSOLE_URL=true
DURATION_SECONDS=3600
REGION="${AWS_REGION:-us-east-1}"

# Base / source profile used for the sts:AssumeRole API call itself. The
# AWS CLI uses this profile's credentials to call AssumeRole; the resulting
# temporary credentials are then written under $PROFILE_NAME. Default to
# the user's SSO admin profile (ptr-tech); overridable via flag or env.
SOURCE_PROFILE="${AWS_SOURCE_PROFILE:-ptr-tech}"

if [[ "$1" == --* ]] && [[ "$1" != "--console-url" ]] && [[ "$1" != "--duration" ]] && [[ "$1" != "--region" ]] && [[ "$1" != "--external-id" ]] && [[ "$1" != "--source-profile" ]]; then
  PROFILE_NAME="${1#--}"
  shift
  if [ -z "$PROFILE_NAME" ]; then
    echo "❌ Empty profile name after '--'."
    usage
    exit 1
  fi
  if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Roles file not found: $ENV_FILE"
    echo "   Expected format (one per line):"
    echo "     profile1=arn:aws:iam::111111111111:role/RoleName"
    echo "     profile2=arn:aws:iam::222222222222:role/OtherRole|optional-external-id"
    exit 1
  fi
  RAW_VALUE=$(grep -E "^[[:space:]]*${PROFILE_NAME}[[:space:]]*=" "$ENV_FILE" 2>/dev/null \
    | head -n1 \
    | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//; s/^'\''//; s/'\''$//')
  if [ -z "$RAW_VALUE" ]; then
    echo "❌ Profile '$PROFILE_NAME' not found in $ENV_FILE"
    usage
    exit 1
  fi
  # Optional inline ExternalId: "<arn>|<external-id>"
  if [[ "$RAW_VALUE" == *"|"* ]]; then
    ROLE_ARN="${RAW_VALUE%%|*}"
    PROFILE_EXTERNAL_ID="${RAW_VALUE#*|}"
    # Trim inner whitespace around the separator.
    ROLE_ARN="${ROLE_ARN%"${ROLE_ARN##*[![:space:]]}"}"
    PROFILE_EXTERNAL_ID="${PROFILE_EXTERNAL_ID#"${PROFILE_EXTERNAL_ID%%[![:space:]]*}"}"
  else
    ROLE_ARN="$RAW_VALUE"
  fi
elif [ -n "$1" ] && [[ "$1" != --* ]] && [ -n "$2" ] && [[ "$2" != --* ]]; then
  ROLE_ARN="$1"
  PROFILE_NAME="$2"
  shift 2
else
  usage
  exit 1
fi

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --console-url)    PRINT_CONSOLE_URL=true ;;
    --no-console-url) PRINT_CONSOLE_URL=false ;;
    --duration)       DURATION_SECONDS="$2"; shift ;;
    --region)         REGION="$2"; shift ;;
    --external-id)    EXTERNAL_ID_CLI="$2"; shift ;;
    --source-profile) SOURCE_PROFILE="$2"; shift ;;
    *) echo "❌ Unknown parameter: $1"; usage; exit 1 ;;
  esac
  shift
done

# CLI flag wins over env-file value.
EXTERNAL_ID="${EXTERNAL_ID_CLI:-$PROFILE_EXTERNAL_ID}"

# Pre-flight: confirm the source profile actually has valid credentials,
# so we surface "go log in" instead of a cryptic ExpiredToken from STS.
if ! aws sts get-caller-identity --profile "$SOURCE_PROFILE" >/dev/null 2>&1; then
  echo "❌ Source profile '$SOURCE_PROFILE' has no valid credentials."
  echo "   Log in first:"
  echo "     ./aws-sso-login.sh --profile $SOURCE_PROFILE"
  echo "   Or pick a different source profile:"
  echo "     $0 --$PROFILE_NAME --source-profile <other-profile>"
  echo "     AWS_SOURCE_PROFILE=<other-profile> $0 --$PROFILE_NAME"
  exit 1
fi

if [ -n "$EXTERNAL_ID" ]; then
  echo "Assuming role: $ROLE_ARN (source: $SOURCE_PROFILE, target profile: $PROFILE_NAME, duration: ${DURATION_SECONDS}s, ExternalId: $EXTERNAL_ID)..."
else
  echo "Assuming role: $ROLE_ARN (source: $SOURCE_PROFILE, target profile: $PROFILE_NAME, duration: ${DURATION_SECONDS}s)..."
fi

ASSUME_ARGS=(
  --role-arn "$ROLE_ARN"
  --role-session-name "$PROFILE_NAME-session"
  --duration-seconds "$DURATION_SECONDS"
)
[ -n "$EXTERNAL_ID" ] && ASSUME_ARGS+=(--external-id "$EXTERNAL_ID")

CREDS=$(aws sts assume-role \
  --profile "$SOURCE_PROFILE" \
  "${ASSUME_ARGS[@]}" \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)

if [ $? -ne 0 ]; then
  echo "❌ Failed to assume role."
  echo "   Common causes:"
  echo "   - Source profile '$SOURCE_PROFILE' lacks sts:AssumeRole permission on $ROLE_ARN"
  echo "   - Role trust policy does not allow this principal"
  echo "   - ExternalId mismatch (set --external-id or fix the env file entry)"
  exit 1
fi

read AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN <<< "$CREDS"

aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID" --profile "$PROFILE_NAME"
aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY" --profile "$PROFILE_NAME"
aws configure set aws_session_token "$AWS_SESSION_TOKEN" --profile "$PROFILE_NAME"

echo "✅ Temporary credentials stored in profile: $PROFILE_NAME"
echo "Test it with:"
echo "aws sts get-caller-identity --profile $PROFILE_NAME"

if [ "$PRINT_CONSOLE_URL" = "true" ]; then
  echo ""
  echo "🌐 Generating AWS Console sign-in URL..."

  CONSOLE_URL=$(AK="$AWS_ACCESS_KEY_ID" SK="$AWS_SECRET_ACCESS_KEY" ST="$AWS_SESSION_TOKEN" \
    REG="$REGION" python3 -c "
import json, os, urllib.request, urllib.error, urllib.parse, sys

# NOTE: when the credentials come from sts:AssumeRole (this script's case),
# the federation endpoint rejects SessionDuration. The console session length
# is implicitly the assumed-role session length.
creds = json.dumps({
    'sessionId':    os.environ['AK'],
    'sessionKey':   os.environ['SK'],
    'sessionToken': os.environ['ST'],
})
signin = 'https://signin.aws.amazon.com/federation'
get_url = signin + '?' + urllib.parse.urlencode({
    'Action': 'getSigninToken',
    'Session': creds,
})
try:
    token = json.loads(urllib.request.urlopen(get_url).read())['SigninToken']
    print(signin + '?' + urllib.parse.urlencode({
        'Action': 'login',
        'Issuer': 'assume-role-to-profile',
        'Destination': 'https://' + os.environ['REG'] + '.console.aws.amazon.com/',
        'SigninToken': token,
    }))
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', 'replace').strip()
    print('ERROR: HTTP ' + str(e.code) + ' from federation endpoint: ' + (body or '<empty body>'), file=sys.stderr)
except Exception as e:
    print('ERROR: ' + str(e), file=sys.stderr)
" 2>&1)

  if [ -n "$CONSOLE_URL" ] && [[ "$CONSOLE_URL" != ERROR:* ]]; then
    echo ""
    echo "🌐 AWS Management Console Sign-in URL:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$CONSOLE_URL"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "⏱️  Valid for ${DURATION_SECONDS}s (region: $REGION)"
    echo "💡 If the console shows the wrong account, use Incognito or sign out first."
  else
    echo "⚠️  Failed to generate console URL."
  fi
fi
