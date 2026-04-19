# BSS Magic Secrets

Place the following file in this directory before running `e2e-deploy.sh`:

## credentials.zip

**Required.** The BSS Magic controller credentials file.

```
starhub-deployer/bssmagic-image/secrets/credentials.zip
```

The `e2e-deploy.sh` script will automatically upload this file to AWS Secrets Manager
on first deploy. If the file is already uploaded (from a previous deploy), it will be skipped.

### How to get credentials.zip

This file is provided by CloudSense. It contains the runtime configuration
for the BSS Magic controller (database connection strings, API keys, etc.).

If you don't have it, contact the CloudSense team.

### Security Note

This file is in `.gitignore` and should NOT be committed to the repository.
It is uploaded to AWS Secrets Manager and fetched by the BSS Magic pod at runtime
via an init container.
