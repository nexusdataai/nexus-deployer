#!/bin/bash

###############################################################################
# GitHub Secrets Updater Script
# 
# This script reads environment variables from .env.local (or .env) and 
# updates GitHub repository secrets using GitHub CLI (gh).
#
# Prerequisites:
#   - GitHub CLI (gh) must be installed and authenticated
#   - .env.local or .env file must exist in project root
#
# Usage:
#   ./scripts/update-github-secrets.sh [ENVIRONMENT]
#
# Arguments:
#   ENVIRONMENT - Target environment: DEV, STAGE, or PROD (default: DEV)
#
# Examples:
#   ./scripts/update-github-secrets.sh          # Updates DEV secrets
#   ./scripts/update-github-secrets.sh STAGE    # Updates STAGE secrets
#   ./scripts/update-github-secrets.sh PROD     # Updates PROD secrets
###############################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default environment
ENVIRONMENT="${1:-DEV}"
ENVIRONMENT=$(echo "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(DEV|STAGE|PROD)$ ]]; then
    echo -e "${RED}❌ Invalid environment: $ENVIRONMENT${NC}"
    echo "Valid options: DEV, STAGE, PROD"
    exit 1
fi

echo -e "${BLUE}🔐 GitHub Secrets Updater${NC}"
echo -e "${BLUE}=========================${NC}"
echo -e "Target Environment: ${GREEN}$ENVIRONMENT${NC}\n"

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo -e "${RED}❌ GitHub CLI (gh) is not installed${NC}"
    echo -e "Install it from: https://cli.github.com/"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo -e "${RED}❌ GitHub CLI is not authenticated${NC}"
    echo -e "Run: ${YELLOW}gh auth login${NC}"
    exit 1
fi

# Find the environment file
ENV_FILE=""
if [ -f ".env.local" ]; then
    ENV_FILE=".env.local"
    echo -e "${GREEN}✓${NC} Found .env.local"
elif [ -f ".env" ]; then
    ENV_FILE=".env"
    echo -e "${GREEN}✓${NC} Found .env"
else
    echo -e "${RED}❌ No .env.local or .env file found${NC}"
    exit 1
fi

echo -e "${BLUE}📄 Reading from: $ENV_FILE${NC}\n"

# Function to update a GitHub secret
update_secret() {
    local secret_name=$1
    local secret_value=$2
    
    if [ -z "$secret_value" ]; then
        echo -e "${YELLOW}⊘${NC} Skipping $secret_name (empty value)"
        return
    fi
    
    echo -e "${BLUE}→${NC} Updating $secret_name..."
    if echo "$secret_value" | gh secret set "$secret_name" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $secret_name updated successfully"
    else
        echo -e "${RED}✗${NC} Failed to update $secret_name"
    fi
}

# Read and parse the environment file
echo -e "${BLUE}🔄 Processing environment variables...${NC}\n"

declare -A env_vars

# Parse the env file
while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    
    # Extract key=value
    if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        
        # Remove quotes if present
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        
        env_vars["$key"]="$value"
    fi
done < "$ENV_FILE"

# Map VITE_ prefixed variables to GitHub secrets with environment suffix
echo -e "${BLUE}📤 Updating GitHub Secrets for $ENVIRONMENT environment...${NC}\n"

# Langflow Primary Configuration
if [ -n "${env_vars[VITE_LANGFLOW_BASE_URL]}" ]; then
    update_secret "LANGFLOW_BASE_URL_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_BASE_URL]}"
fi

if [ -n "${env_vars[VITE_LANGFLOW_FLOW_ID]}" ]; then
    update_secret "LANGFLOW_FLOW_ID_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FLOW_ID]}"
fi

if [ -n "${env_vars[VITE_LANGFLOW_API_KEY]}" ]; then
    update_secret "LANGFLOW_API_KEY_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_API_KEY]}"
fi

# Langflow Fallback Configuration 1
if [ -n "${env_vars[VITE_LANGFLOW_FALLBACK_BASE_URL]}" ]; then
    update_secret "LANGFLOW_FALLBACK_BASE_URL_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FALLBACK_BASE_URL]}"
fi

if [ -n "${env_vars[VITE_LANGFLOW_FALLBACK_FLOW_ID]}" ]; then
    update_secret "LANGFLOW_FALLBACK_FLOW_ID_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FALLBACK_FLOW_ID]}"
fi

if [ -n "${env_vars[VITE_LANGFLOW_FALLBACK_API_KEY]}" ]; then
    update_secret "LANGFLOW_FALLBACK_API_KEY_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FALLBACK_API_KEY]}"
fi

# Langflow Fallback Configuration 2
if [ -n "${env_vars[VITE_LANGFLOW_FALLBACK2_BASE_URL]}" ]; then
    update_secret "LANGFLOW_FALLBACK2_BASE_URL_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FALLBACK2_BASE_URL]}"
fi

if [ -n "${env_vars[VITE_LANGFLOW_FALLBACK2_FLOW_ID]}" ]; then
    update_secret "LANGFLOW_FALLBACK2_FLOW_ID_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FALLBACK2_FLOW_ID]}"
fi

if [ -n "${env_vars[VITE_LANGFLOW_FALLBACK2_API_KEY]}" ]; then
    update_secret "LANGFLOW_FALLBACK2_API_KEY_${ENVIRONMENT}" "${env_vars[VITE_LANGFLOW_FALLBACK2_API_KEY]}"
fi

# OpenAI API Key
if [ -n "${env_vars[VITE_OPENAI_API_KEY]}" ]; then
    update_secret "OPENAI_API_KEY_${ENVIRONMENT}" "${env_vars[VITE_OPENAI_API_KEY]}"
fi

# MCP Host URL
if [ -n "${env_vars[VITE_MCP_HOST_URL]}" ]; then
    update_secret "MCP_HOST_URL_${ENVIRONMENT}" "${env_vars[VITE_MCP_HOST_URL]}"
fi

# AWS Role (if present)
if [ -n "${env_vars[AWS_ROLE_TO_ASSUME]}" ]; then
    update_secret "AWS_ROLE_TO_ASSUME_${ENVIRONMENT}" "${env_vars[AWS_ROLE_TO_ASSUME]}"
fi

echo -e "\n${GREEN}✅ GitHub Secrets update complete for $ENVIRONMENT environment!${NC}"
echo -e "\n${BLUE}ℹ️  To verify secrets, run:${NC}"
echo -e "   ${YELLOW}gh secret list${NC}"
