#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ENV_FILE="$SCRIPT_DIR/.env.roles.local"

usage() {
  echo "Usage:"
  echo "  $0 --<profile-name> [--console-url] [--duration N] [--region R]"
  echo "  $0 <role-arn> <profile-name> [--console-url] [--duration N] [--region R]"
  echo ""
  echo "Options:"
  echo "  --console-url   Generate AWS Console sign-in URL for the assumed role"
  echo "  --duration N    STS session duration in seconds (default: 3600, role MaxSessionDuration permitting)"
  echo "  --region R      Region for the console destination URL (default: \$AWS_REGION or us-east-1)"
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
PRINT_CONSOLE_URL=false
DURATION_SECONDS=3600
REGION="${AWS_REGION:-us-east-1}"

if [[ "$1" == --* ]] && [[ "$1" != "--console-url" ]] && [[ "$1" != "--duration" ]] && [[ "$1" != "--region" ]]; then
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
    echo "     profile2=arn:aws:iam::222222222222:role/OtherRole"
    exit 1
  fi
  ROLE_ARN=$(grep -E "^[[:space:]]*${PROFILE_NAME}[[:space:]]*=" "$ENV_FILE" 2>/dev/null \
    | head -n1 \
    | sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//; s/^'\''//; s/'\''$//')
  if [ -z "$ROLE_ARN" ]; then
    echo "❌ Profile '$PROFILE_NAME' not found in $ENV_FILE"
    usage
    exit 1
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
    --console-url) PRINT_CONSOLE_URL=true ;;
    --duration)    DURATION_SECONDS="$2"; shift ;;
    --region)      REGION="$2"; shift ;;
    *) echo "❌ Unknown parameter: $1"; usage; exit 1 ;;
  esac
  shift
done

echo "Assuming role: $ROLE_ARN (profile: $PROFILE_NAME, duration: ${DURATION_SECONDS}s)..."

CREDS=$(aws sts assume-role \
  --role-arn "$ROLE_ARN" \
  --role-session-name "$PROFILE_NAME-session" \
  --duration-seconds "$DURATION_SECONDS" \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)

if [ $? -ne 0 ]; then
  echo "❌ Failed to assume role."
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
    DUR="$DURATION_SECONDS" REG="$REGION" python3 -c "
import json, os, urllib.request, urllib.parse, sys

creds = json.dumps({
    'sessionId':    os.environ['AK'],
    'sessionKey':   os.environ['SK'],
    'sessionToken': os.environ['ST'],
})
signin = 'https://signin.aws.amazon.com/federation'
get_url = signin + '?' + urllib.parse.urlencode({
    'Action': 'getSigninToken',
    'SessionDuration': os.environ['DUR'],
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
except Exception as e:
    print('ERROR: ' + str(e), file=sys.stderr)
")

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
