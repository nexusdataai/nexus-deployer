#!/usr/bin/env python3

"""
GitHub Secrets Updater Script

This script reads environment variables from .env.local (or .env) and 
updates GitHub repository secrets using GitHub CLI (gh).

Prerequisites:
    - GitHub CLI (gh) must be installed and authenticated
    - .env.local or .env file must exist in project root

Usage:
    python scripts/update-github-secrets.py [ENVIRONMENT] [--dry-run]

Arguments:
    ENVIRONMENT - Target environment: DEV, STAGE, or PROD (default: DEV)
    --dry-run   - Preview changes without actually updating secrets

Examples:
    python scripts/update-github-secrets.py          # Updates DEV secrets
    python scripts/update-github-secrets.py STAGE    # Updates STAGE secrets
    python scripts/update-github-secrets.py PROD     # Updates PROD secrets
    python scripts/update-github-secrets.py DEV --dry-run  # Preview DEV changes
"""

import os
import sys
import subprocess
import re
import argparse
from pathlib import Path
from typing import Dict, Optional

# ANSI color codes
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


def print_error(message: str) -> None:
    """Print error message in red."""
    print(f"{Colors.RED}❌ {message}{Colors.NC}")


def print_success(message: str) -> None:
    """Print success message in green."""
    print(f"{Colors.GREEN}✓ {message}{Colors.NC}")


def print_info(message: str) -> None:
    """Print info message in blue."""
    print(f"{Colors.BLUE}{message}{Colors.NC}")


def print_warning(message: str) -> None:
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}⊘ {message}{Colors.NC}")


def check_gh_cli() -> bool:
    """Check if GitHub CLI is installed and authenticated."""
    try:
        subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("GitHub CLI (gh) is not installed")
        print("Install it from: https://cli.github.com/")
        return False
    
    try:
        subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError:
        print_error("GitHub CLI is not authenticated")
        print(f"Run: {Colors.YELLOW}gh auth login{Colors.NC}")
        return False
    
    return True


def find_env_file() -> Optional[Path]:
    """Find the environment file (.env.local or .env)."""
    project_root = Path(__file__).parent.parent
    
    env_local = project_root / ".env.local"
    if env_local.exists():
        print_success("Found .env.local")
        return env_local
    
    env_file = project_root / ".env"
    if env_file.exists():
        print_success("Found .env")
        return env_file
    
    print_error("No .env.local or .env file found")
    return None


def parse_env_file(env_file: Path) -> Dict[str, str]:
    """Parse environment file and return key-value pairs."""
    env_vars = {}
    
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Match KEY=VALUE pattern
            match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line)
            if match:
                key = match.group(1)
                value = match.group(2)
                
                # Remove surrounding quotes
                value = value.strip('"').strip("'")
                
                env_vars[key] = value
    
    return env_vars


def update_secret(secret_name: str, secret_value: str, dry_run: bool = False) -> bool:
    """Update a GitHub secret using gh CLI."""
    if not secret_value:
        print_warning(f"Skipping {secret_name} (empty value)")
        return False
    
    # Mask the secret value for display (show first 8 chars + ...)
    masked_value = f"{secret_value[:8]}..." if len(secret_value) > 8 else "***"
    
    if dry_run:
        print_info(f"→ [DRY RUN] Would update {secret_name} = {masked_value}")
        return True
    
    print_info(f"→ Updating {secret_name}...")
    
    try:
        process = subprocess.Popen(
            ["gh", "secret", "set", secret_name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(input=secret_value)
        
        if process.returncode == 0:
            print_success(f"{secret_name} updated successfully")
            return True
        else:
            print_error(f"Failed to update {secret_name}: {stderr}")
            return False
            
    except Exception as e:
        print_error(f"Failed to update {secret_name}: {str(e)}")
        return False


def main():
    """Main function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Update GitHub repository secrets from local .env file",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "environment",
        nargs="?",
        default="DEV",
        choices=["DEV", "STAGE", "PROD"],
        help="Target environment (default: DEV)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without updating secrets"
    )
    
    args = parser.parse_args()
    environment = args.environment.upper()
    dry_run = args.dry_run
    
    print(f"\n{Colors.BLUE}🔐 GitHub Secrets Updater{Colors.NC}")
    print(f"{Colors.BLUE}========================={Colors.NC}")
    print(f"Target Environment: {Colors.GREEN}{environment}{Colors.NC}")
    if dry_run:
        print(f"Mode: {Colors.YELLOW}DRY RUN (no changes will be made){Colors.NC}\n")
    else:
        print()
    
    # Check prerequisites
    if not check_gh_cli():
        sys.exit(1)
    
    # Find environment file
    env_file = find_env_file()
    if not env_file:
        sys.exit(1)
    
    print_info(f"📄 Reading from: {env_file.name}\n")
    
    # Parse environment file
    env_vars = parse_env_file(env_file)
    
    if not env_vars:
        print_error("No environment variables found in file")
        sys.exit(1)
    
    print_info(f"🔄 Processing {len(env_vars)} environment variables...\n")
    print_info(f"📤 Updating GitHub Secrets for {environment} environment...\n")
    
    # Define secret mappings (local var -> GitHub secret prefix)
    secret_mappings = [
        # Langflow Primary Configuration
        ("VITE_LANGFLOW_BASE_URL", f"LANGFLOW_BASE_URL_{environment}"),
        ("VITE_LANGFLOW_FLOW_ID", f"LANGFLOW_FLOW_ID_{environment}"),
        ("VITE_LANGFLOW_API_KEY", f"LANGFLOW_API_KEY_{environment}"),
        
        # Langflow Fallback Configuration 1
        ("VITE_LANGFLOW_FALLBACK_BASE_URL", f"LANGFLOW_FALLBACK_BASE_URL_{environment}"),
        ("VITE_LANGFLOW_FALLBACK_FLOW_ID", f"LANGFLOW_FALLBACK_FLOW_ID_{environment}"),
        ("VITE_LANGFLOW_FALLBACK_API_KEY", f"LANGFLOW_FALLBACK_API_KEY_{environment}"),
        
        # Langflow Fallback Configuration 2
        ("VITE_LANGFLOW_FALLBACK2_BASE_URL", f"LANGFLOW_FALLBACK2_BASE_URL_{environment}"),
        ("VITE_LANGFLOW_FALLBACK2_FLOW_ID", f"LANGFLOW_FALLBACK2_FLOW_ID_{environment}"),
        ("VITE_LANGFLOW_FALLBACK2_API_KEY", f"LANGFLOW_FALLBACK2_API_KEY_{environment}"),
        
        # OpenAI API Key
        ("VITE_OPENAI_API_KEY", f"OPENAI_API_KEY_{environment}"),
        
        # MCP Host URL
        ("VITE_MCP_HOST_URL", f"MCP_HOST_URL_{environment}"),
        
        # AWS Role
        ("AWS_ROLE_TO_ASSUME", f"AWS_ROLE_TO_ASSUME_{environment}"),
    ]
    
    # Update secrets
    updated_count = 0
    for local_key, github_secret in secret_mappings:
        if local_key in env_vars:
            if update_secret(github_secret, env_vars[local_key], dry_run=dry_run):
                updated_count += 1
    
    if dry_run:
        print(f"\n{Colors.YELLOW}✅ Dry run complete for {environment} environment!{Colors.NC}")
        print(f"{Colors.YELLOW}   Would update {updated_count} secrets{Colors.NC}")
        print(f"\n{Colors.BLUE}Run without --dry-run to actually update the secrets.{Colors.NC}\n")
    else:
        print(f"\n{Colors.GREEN}✅ GitHub Secrets update complete for {environment} environment!{Colors.NC}")
        print(f"{Colors.GREEN}   Updated {updated_count} secrets{Colors.NC}\n")
        print_info("ℹ️  To verify secrets, run:")
        print(f"   {Colors.YELLOW}gh secret list{Colors.NC}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⚠️  Operation cancelled by user{Colors.NC}")
        sys.exit(130)
    except Exception as e:
        print_error(f"Unexpected error: {str(e)}")
        sys.exit(1)
