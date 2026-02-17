---
DEPRECATED: This document refers to an old architecture based on Oracle Cloud Infrastructure (OCI) and is kept for historical purposes only. The current architecture runs on AWS.
---

# Secrets Management

This document defines the secret inventory, rotation procedures, and incident response for the homelab infrastructure.

**AWS Equivalent:** This document serves as the Secrets Manager rotation policy and runbooks as defined in AWS DevOps Engineer - Professional (DOP-C02) best practices.

---

## Secrets Inventory

| Secret Type | Location | Purpose | Rotation Interval | Last Rotated | Next Rotation |
|-------------|----------|---------|-------------------|--------------|---------------|
| GitHub PAT | `~/.config/gh/hosts.yml` | GitHub CLI authentication, PR automation | 90 days | 2026-01-17 | 2026-04-17 |
| ArgoCD SSH Key | `k8s/gitops/ssh/argocd` | GitOps repository access | 180 days | 2026-01-24 | 2026-07-23 |
| OCI API Key | `~/.oci/oci_api_key.pem` | Oracle Cloud infrastructure access | 365 days | 2026-01-10 | 2027-01-10 |

**Notes:**
- All secrets are stored with restrictive permissions (`600` or `700`)
- Secrets are excluded from git via `.gitignore`
- No secrets are stored in Kubernetes manifests (use sealed-secrets or external-secrets for cluster secrets)

---

## Rotation Procedures

### GitHub Personal Access Token (PAT)

**Rotation Interval:** 90 days

**Procedure:**
1. Generate new PAT at: https://github.com/settings/tokens
   - Scopes required: `repo`, `read:org`, `workflow`
   - Expiration: 90 days
2. Update local GitHub CLI configuration:
   ```bash
   gh auth login
   # Select: GitHub.com -> Paste authentication token -> <paste new PAT>
   ```
3. Verify authentication:
   ```bash
   gh auth status
   ```
4. Test PR operations:
   ```bash
   gh pr list
   ```
5. Update "Last Rotated" date in this document
6. Delete old PAT from GitHub settings

**Rollback:** If new PAT fails, regenerate old PAT from GitHub settings and run `gh auth login` again.

---

### ArgoCD SSH Key

**Rotation Interval:** 180 days

**Procedure:**
1. Generate new SSH key pair:
   ```bash
   ssh-keygen -t ed25519 -C "argocd@homelab" -f ~/.ssh/argocd_new
   ```
2. Add new public key to GitHub repository:
   - Navigate to: Settings → Deploy keys → Add deploy key
   - Title: `ArgoCD GitOps - Rotated $(date +%Y-%m-%d)`
   - Key: `cat ~/.ssh/argocd_new.pub`
   - Allow write access: **No** (read-only)
3. Update ArgoCD secret in Kubernetes:
   ```bash
   kubectl create secret generic argocd-repo-creds \
     --from-file=sshPrivateKey=~/.ssh/argocd_new \
     --dry-run=client -o yaml | kubectl apply -n argocd -f -
   ```
4. Verify ArgoCD can sync:
   ```bash
   argocd app sync homelab-apps-root
   ```
5. If successful, update `k8s/gitops/ssh/argocd` with new key:
   ```bash
   cp ~/.ssh/argocd_new k8s/gitops/ssh/argocd
   chmod 600 k8s/gitops/ssh/argocd
   ```
6. Delete old deploy key from GitHub
7. Update "Last Rotated" date in this document

**Rollback:** Re-add old public key to GitHub deploy keys and revert Kubernetes secret.

---

### OCI API Key

**Rotation Interval:** 365 days

**Procedure:**
1. Generate new API key pair:
   ```bash
   openssl genrsa -out ~/.oci/oci_api_key_new.pem 2048
   openssl rsa -pubout -in ~/.oci/oci_api_key_new.pem -out ~/.oci/oci_api_key_new_public.pem
   chmod 600 ~/.oci/oci_api_key_new.pem
   ```
2. Upload new public key to OCI Console:
   - Navigate to: User Settings → API Keys → Add API Key
   - Upload: `~/.oci/oci_api_key_new_public.pem`
3. Update OCI CLI configuration:
   ```bash
   vim ~/.oci/config
   # Update key_file path to ~/.oci/oci_api_key_new.pem
   ```
4. Verify authentication:
   ```bash
   oci iam region list
   ```
5. Test infrastructure operations:
   ```bash
   oci compute instance list --compartment-id <compartment-ocid>
   ```
6. If successful, replace old key:
   ```bash
   mv ~/.oci/oci_api_key_new.pem ~/.oci/oci_api_key.pem
   ```
7. Delete old API key from OCI Console
8. Update "Last Rotated" date in this document

**Rollback:** Re-upload old public key to OCI Console and revert `~/.oci/config` changes.

---

## Incident Response Procedures

### Suspected Secret Exposure

**Severity:** 🔴 **CRITICAL**

**Immediate Actions (within 1 hour):**
1. **Identify scope:**
   - Which secret(s) were exposed?
   - Where was it exposed? (git commit, logs, screenshot, chat)
   - Who has access to the exposure location?
2. **Revoke compromised secret immediately:**
   - GitHub PAT: Revoke at https://github.com/settings/tokens
   - ArgoCD SSH: Delete deploy key from GitHub
   - OCI API Key: Delete from OCI Console → User Settings → API Keys
3. **Generate and deploy new secret** (follow rotation procedures above)
4. **Verify revocation:**
   - Attempt authentication with old secret (should fail)
   - Check audit logs for unauthorized access
5. **Document incident** in `.opencode/memory.md`:
   ```markdown
   ### Secret Exposure Incident - <date>
   **Secret Type:** <GitHub PAT / ArgoCD SSH / OCI API Key>
   **Exposure Location:** <git commit hash / log file / etc.>
   **Actions Taken:** <summary of remediation>
   **Duration:** <time from exposure to revocation>
   ```

**Follow-up Actions (within 24 hours):**
1. **Remove secret from exposure location:**
   - If in git: Use BFG Repo-Cleaner or `git filter-branch` to rewrite history
   - If in logs: Purge logs and restart affected services
   - If in external system: Contact system administrator for removal
2. **Audit recent activity:**
   - GitHub: Check repository access logs
   - OCI: Review audit logs for unauthorized API calls
   - ArgoCD: Check sync history for unexpected changes
3. **Assess damage:**
   - Were any unauthorized changes made?
   - Was any data exfiltrated?
   - Do other secrets need rotation?
4. **Update security measures:**
   - Add secret to `.gitignore` if not already present
   - Implement pre-commit hooks to detect secrets
   - Review access controls

**Escalation:** If unauthorized access detected, consider rotating ALL secrets and enabling MFA on all accounts.

---

## Audit Schedule

### Monthly Checks (1st of each month)

- [ ] Verify all secrets have correct file permissions (`600`)
- [ ] Check GitHub PAT expiration date (renew if <30 days remaining)
- [ ] Review ArgoCD sync logs for authentication failures
- [ ] Verify OCI API key is functional (`oci iam region list`)

### Quarterly Reviews (January, April, July, October)

- [ ] Review secrets inventory for accuracy
- [ ] Update rotation dates in this document
- [ ] Test rollback procedures for each secret type
- [ ] Review incident response runbooks for completeness
- [ ] Check for unused or orphaned secrets

---

## Adding New Secrets

When adding new secrets to the homelab infrastructure:

1. **Document in inventory table** (add row with all required fields)
2. **Define rotation interval** based on criticality:
   - Critical (cluster admin, root access): 90 days
   - High (application access, CI/CD): 180 days
   - Medium (read-only, monitoring): 365 days
3. **Create rotation procedure** (step-by-step with rollback plan)
4. **Add to `.gitignore`** to prevent accidental commits
5. **Set restrictive permissions** (`chmod 600` for files)
6. **Test rotation procedure** before next scheduled rotation
7. **Add to monthly/quarterly audit checklist**

---

**Last Updated:** 2026-01-25
**Document Owner:** Tech Lead
**Review Frequency:** Quarterly
