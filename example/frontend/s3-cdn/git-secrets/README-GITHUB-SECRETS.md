# 🔐 GitHub Secrets Automation Scripts

Automated scripts to sync your local environment variables to GitHub repository secrets.

## 📋 Overview

These scripts read environment variables from your local `.env.local` (or `.env`) file and automatically update the corresponding GitHub repository secrets for your target environment (DEV, STAGE, or PROD).

## 🔧 Prerequisites

### Required Tools

1. **GitHub CLI (gh)**
   ```bash
   # Install on macOS
   brew install gh
   
   # Install on Linux
   curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
   sudo apt update
   sudo apt install gh
   
   # Install on Windows
   winget install --id GitHub.cli
   ```

2. **Authenticate GitHub CLI**
   ```bash
   gh auth login
   ```
   Follow the prompts to authenticate with your GitHub account.

### Required Files

- `.env.local` or `.env` file in the project root containing your environment variables

## 🚀 Usage

### Bash Script

```bash
# Update DEV environment secrets (default)
./scripts/update-github-secrets.sh

# Update STAGE environment secrets
./scripts/update-github-secrets.sh STAGE

# Update PROD environment secrets
./scripts/update-github-secrets.sh PROD
```

### Python Script

```bash
# Update DEV environment secrets (default)
python scripts/update-github-secrets.py

# Update STAGE environment secrets
python scripts/update-github-secrets.py STAGE

# Update PROD environment secrets
python scripts/update-github-secrets.py PROD

# Preview changes without updating (dry-run)
python scripts/update-github-secrets.py DEV --dry-run
python scripts/update-github-secrets.py PROD --dry-run
```

## 📝 Environment Variable Mapping

The scripts automatically map your local environment variables to GitHub secrets:

| Local Variable (.env.local)              | GitHub Secret (DEV)                   |
|-----------------------------------------|---------------------------------------|
| `VITE_LANGFLOW_BASE_URL`                | `LANGFLOW_BASE_URL_DEV`              |
| `VITE_LANGFLOW_FLOW_ID`                 | `LANGFLOW_FLOW_ID_DEV`               |
| `VITE_LANGFLOW_API_KEY`                 | `LANGFLOW_API_KEY_DEV`               |
| `VITE_LANGFLOW_FALLBACK_BASE_URL`       | `LANGFLOW_FALLBACK_BASE_URL_DEV`     |
| `VITE_LANGFLOW_FALLBACK_FLOW_ID`        | `LANGFLOW_FALLBACK_FLOW_ID_DEV`      |
| `VITE_LANGFLOW_FALLBACK_API_KEY`        | `LANGFLOW_FALLBACK_API_KEY_DEV`      |
| `VITE_LANGFLOW_FALLBACK2_BASE_URL`      | `LANGFLOW_FALLBACK2_BASE_URL_DEV`    |
| `VITE_LANGFLOW_FALLBACK2_FLOW_ID`       | `LANGFLOW_FALLBACK2_FLOW_ID_DEV`     |
| `VITE_LANGFLOW_FALLBACK2_API_KEY`       | `LANGFLOW_FALLBACK2_API_KEY_DEV`     |
| `VITE_OPENAI_API_KEY`                   | `OPENAI_API_KEY_DEV`                 |
| `VITE_MCP_HOST_URL`                     | `MCP_HOST_URL_DEV`                   |
| `AWS_ROLE_TO_ASSUME`                    | `AWS_ROLE_TO_ASSUME_DEV`             |

> **Note**: For STAGE and PROD environments, the suffix changes to `_STAGE` and `_PROD` respectively.

## 🔍 Example Workflow

### 1. Create your local environment file

Create `.env.local` in the project root:

```bash
# Primary Langflow Configuration
VITE_LANGFLOW_BASE_URL=https://studio.cps.bssmagic.io
VITE_LANGFLOW_FLOW_ID=89f71104-1c2e-44a8-8e78-716637054c19
VITE_LANGFLOW_API_KEY=your_api_key_here

# Fallback Configuration 1
VITE_LANGFLOW_FALLBACK_BASE_URL=https://studio.cps.bssmagic.io
VITE_LANGFLOW_FALLBACK_FLOW_ID=a07536c3-ba2d-43a6-927d-be605aeb7e6c
VITE_LANGFLOW_FALLBACK_API_KEY=your_fallback_api_key_here

# Fallback Configuration 2
VITE_LANGFLOW_FALLBACK2_BASE_URL=https://studio.bssmagic.io
VITE_LANGFLOW_FALLBACK2_FLOW_ID=dce1eada-9bf0-4ab8-98e5-72190a315fd3
VITE_LANGFLOW_FALLBACK2_API_KEY=your_alternative_api_key_here

# OpenAI Configuration
VITE_OPENAI_API_KEY=sk-proj-xxxxx

# MCP Configuration
VITE_MCP_HOST_URL=https://api.dev-alert-engine.totogicore.com
```

### 2. Run the script

```bash
# For development environment
./scripts/update-github-secrets.sh DEV
```

### 3. Preview changes (optional)

```bash
# Preview what would be updated without making changes
python scripts/update-github-secrets.py DEV --dry-run
```

### 4. Update the secrets

```bash
# Actually update the secrets
./scripts/update-github-secrets.sh DEV
```

### 5. Verify the secrets were created

```bash
gh secret list
```

## 🔍 Dry Run Mode (Python Script Only)

The Python script supports a `--dry-run` flag to preview changes without actually updating secrets:

```bash
python scripts/update-github-secrets.py DEV --dry-run
```

This will:
- Show which secrets would be updated
- Display masked values for security
- Not make any actual changes to GitHub

Use this to:
- Preview changes before committing
- Verify your `.env.local` file is correctly formatted
- Check which secrets are missing or empty

## 📊 Script Output

Both scripts provide colorized output showing:

- ✅ **Success**: Secrets updated successfully
- ⊘ **Skipped**: Empty values (not updated)
- ❌ **Error**: Failed operations with error messages

### Example Output

```
🔐 GitHub Secrets Updater
=========================
Target Environment: DEV

✓ Found .env.local
📄 Reading from: .env.local

🔄 Processing environment variables...

📤 Updating GitHub Secrets for DEV environment...

→ Updating LANGFLOW_BASE_URL_DEV...
✓ LANGFLOW_BASE_URL_DEV updated successfully
→ Updating LANGFLOW_FLOW_ID_DEV...
✓ LANGFLOW_FLOW_ID_DEV updated successfully
→ Updating LANGFLOW_API_KEY_DEV...
✓ LANGFLOW_API_KEY_DEV updated successfully

✅ GitHub Secrets update complete for DEV environment!

ℹ️  To verify secrets, run:
   gh secret list
```

## 🛡️ Security Best Practices

1. **Never commit** `.env.local` or `.env` files to version control
2. **Use different secrets** for DEV, STAGE, and PROD environments
3. **Rotate secrets regularly**, especially after team member changes
4. **Review permissions** - ensure only authorized personnel can update production secrets
5. **Audit changes** - monitor secret updates through GitHub's audit log

## 🔧 Troubleshooting

### GitHub CLI Not Authenticated

**Error**: `❌ GitHub CLI is not authenticated`

**Solution**:
```bash
gh auth login
```

### Environment File Not Found

**Error**: `❌ No .env.local or .env file found`

**Solution**: Create a `.env.local` file in the project root with your environment variables.

### Permission Denied

**Error**: `Permission denied: ./scripts/update-github-secrets.sh`

**Solution**:
```bash
chmod +x scripts/update-github-secrets.sh
```

### Secret Update Failed

**Error**: `✗ Failed to update SECRET_NAME`

**Possible causes**:
- Insufficient GitHub permissions
- Repository not found
- Network issues

**Solution**: Check your GitHub permissions and ensure you have admin access to the repository.

## 🔄 Integration with CI/CD

These scripts are designed to work alongside your GitHub Actions workflows. Use them to:

1. **Initial setup**: Quickly populate all required secrets
2. **Environment sync**: Keep local and GitHub secrets in sync
3. **Secret rotation**: Easily update secrets across all environments

## 📚 Related Documentation

- [GITHUB_SECRETS_HA_SETUP.md](../GITHUB_SECRETS_HA_SETUP.md) - Detailed GitHub Secrets setup guide
- [LANGFLOW_HA_GUIDE.md](../LANGFLOW_HA_GUIDE.md) - Langflow High Availability guide
- [env.example.ha](../env.example.ha) - Example environment file template

## 🎯 Quick Reference

| Command | Description |
|---------|-------------|
| `./scripts/update-github-secrets.sh` | Update DEV secrets (Bash) |
| `./scripts/update-github-secrets.sh STAGE` | Update STAGE secrets (Bash) |
| `./scripts/update-github-secrets.sh PROD` | Update PROD secrets (Bash) |
| `python scripts/update-github-secrets.py` | Update DEV secrets (Python) |
| `python scripts/update-github-secrets.py STAGE` | Update STAGE secrets (Python) |
| `python scripts/update-github-secrets.py PROD` | Update PROD secrets (Python) |
| `python scripts/update-github-secrets.py DEV --dry-run` | Preview DEV changes without updating |
| `gh secret list` | List all repository secrets |
| `gh secret set SECRET_NAME` | Manually set a secret |
| `gh secret remove SECRET_NAME` | Delete a secret |

---

**Need help?** Check the [troubleshooting](#-troubleshooting) section or open an issue on GitHub.
