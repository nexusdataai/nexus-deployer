# Security incident: hard-coded ADFS test credentials (resolved in working tree)

## Summary

During SAST remediation we discovered hard-coded ADFS credentials in two
manual test scripts on the `stage` branch:

- `backend/test_adfs.py` (lines 13-15 of the original file)
- `backend/test_adfs_full.py` (lines 12-15 of the original file)

The leaked values referenced an internal `devfactory.com` ADFS account.

## Working-tree fix

Both files now read `ADFS_TEST_USERNAME`, `ADFS_TEST_PASSWORD` (and related
host / URL / region) from environment variables. If the env vars are unset
the script exits with code 2.

## Action items for the security team

1. **Rotate the leaked credentials immediately.** Treat them as compromised.
2. **Purge the history.** The literal values remain in the git history of
   the `stage` branch and in any prior backups. After rotation, run
   `git-filter-repo --replace-text expressions.txt` (or BFG) and force-push
   `stage` once approved. Notify all consumers.
3. **Audit logs.** Review ADFS / AWS CloudTrail for the impacted account
   over the period the secret was committed.

## Detection going forward

The `.secrets.baseline` plus the pre-commit and CI hooks added in the SAST
remediation work will fail the build on new commits containing
secret-shaped strings.
