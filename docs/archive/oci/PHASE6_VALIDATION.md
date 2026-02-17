---
DEPRECATED: This document refers to an old architecture based on Oracle Cloud Infrastructure (OCI) and is kept for historical purposes only. The current architecture runs on AWS.
---

# Phase 6 Validation Guide

## Post-Deployment Validation Checklist

This document provides step-by-step validation procedures after applying Phase 6 changes.

## Prerequisites

- ✅ SSH public key added to GitHub Deploy Keys
- ✅ `k8s/gitops/apply-phase6-gitops.sh` executed successfully
- ✅ Wait 5 minutes for ArgoCD to process changes

## Validation Steps

### 1. Verify ArgoCD Repository Secret

**Check if the secret exists:**

```bash
kubectl get secret argocd-repo-homelab -n argocd
```

**Expected Output:**
```
NAME                   TYPE     DATA   AGE
argocd-repo-homelab    Opaque   2      5m
```

**Check secret labels (ArgoCD auto-discovery):**

```bash
kubectl get secret argocd-repo-homelab -n argocd -o jsonpath='{.metadata.labels}' | jq
```

**Expected Output:**
```json
{
  "app.kubernetes.io/name": "argocd-repo-homelab",
  "app.kubernetes.io/part-of": "homelab",
  "argocd.argoproj.io/secret-type": "repository"
}
```

**CRITICAL:** The label `argocd.argoproj.io/secret-type: repository` is **required** for ArgoCD to auto-discover the credentials.

---

### 2. Verify App-of-Apps Configuration

**Check the source URL and target branch:**

```bash
kubectl get application homelab-apps-root -n argocd -o jsonpath='{.spec.source}' | jq
```

**Expected Output:**
```json
{
  "path": "k8s/apps",
  "repoURL": "git@github.com:ariel99gf/homelab.git",
  "targetRevision": "develop"
}
```

**Verify Annotations:**
- ✅ `repoURL` is SSH format: `git@github.com:...`
- ✅ `targetRevision` is `develop` (not `HEAD`)

---

### 3. Check ArgoCD Application Status

**List all applications:**

```bash
kubectl get applications -n argocd
```

**Expected Output:**
```
NAME                  SYNC STATUS   HEALTH STATUS
homelab-apps-root     Synced        Healthy
adguard-home         Synced        Healthy
grafana              Synced        Healthy
loki                 Synced        Healthy
prometheus           Synced        Healthy
searxng              Synced        Healthy
golink               Synced        Healthy
```

**If any application shows `OutOfSync` or `Progressing`:**

```bash
# Force refresh
kubectl patch application <app-name> -n argocd \
  --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'

# Watch status
kubectl get applications -n argocd -w
```

---

### 4. Verify SSH Connection (ArgoCD Logs)

**Check ArgoCD repository server logs for SSH authentication:**

```bash
kubectl logs -n argocd deployment/argocd-repo-server --tail=100 | grep -i "ssh\|git\|auth"
```

**Expected Output (Successful SSH):**
```
time="2026-01-23T13:20:15Z" level=info msg="Successfully connected to git@github.com:ariel99gf/homelab.git"
time="2026-01-23T13:20:16Z" level=info msg="Fetched revision develop (commit: 4a2b3c4)"
```

**Error Indicators (Troubleshooting Required):**
```
❌ "Host key verification failed" → Missing known_hosts configuration
❌ "Permission denied (publickey)" → SSH key not added to GitHub Deploy Keys
❌ "Could not resolve hostname github.com" → DNS issues
```

---

### 5. Test GitHub Deploy Key Permissions

**Verify the Deploy Key is read-only:**

```bash
# Attempt to push (should fail)
kubectl exec -n argocd deployment/argocd-repo-server -- \
  git ls-remote git@github.com:ariel99gf/homelab.git HEAD
```

**Expected Output:**
```
4a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t    HEAD
```

**If this fails with "Permission denied":**
- Check if the SSH public key was added to GitHub Deploy Keys
- Verify the key format (should start with `ssh-ed25519 AAAAC3Nza...`)

---

### 6. Monitor ArgoCD Sync Operations

**Watch ArgoCD application sync status in real-time:**

```bash
kubectl get applications -n argocd -w
```

**Expected Behavior:**
- All applications transition to `Synced` within 3-5 minutes
- Health status transitions to `Healthy` within 1-2 minutes after sync

**If applications remain in `OutOfSync` after 10 minutes:**

```bash
# Check ArgoCD application controller logs
kubectl logs -n argocd deployment/argocd-application-controller --tail=100

# Describe the problematic application
kubectl describe application <app-name> -n argocd
```

---

### 7. Verify Automatic Sync Policy

**Check if automated sync is enabled:**

```bash
kubectl get application homelab-apps-root -n argocd -o jsonpath='{.spec.syncPolicy}' | jq
```

**Expected Output:**
```json
{
  "automated": {
    "prune": true,
    "selfHeal": true,
    "allowEmpty": false
  },
  "syncOptions": [
    "CreateNamespace=true",
    "PrunePropagationPolicy=foreground",
    "PruneLast=true"
  ],
  "retry": {
    "limit": 5,
    "backoff": {
      "duration": "5s",
      "factor": 2,
      "maxDuration": "3m"
    }
  }
}
```

**Verify Annotations:**
- ✅ `prune: true` - Deletes resources removed from Git
- ✅ `selfHeal: true` - Auto-syncs on drift detection
- ✅ `allowEmpty: false` - Prevents accidental deletion of all resources

---

### 8. Test Drift Detection (Self-Heal)

**Simulate configuration drift:**

```bash
# Manually scale a deployment
kubectl scale deployment prometheus -n observability --replicas=0

# Wait 30 seconds for ArgoCD to detect drift
sleep 30

# Check if ArgoCD auto-corrected the drift
kubectl get deployment prometheus -n observability -o jsonpath='{.spec.replicas}'
```

**Expected Output:**
```
1
```

**If replicas remain at 0:**
- Check ArgoCD logs for sync errors
- Verify `selfHeal: true` is enabled (step 7)
- Check if the deployment is ignored via `ignoreDifferences`

---

## Troubleshooting Guide

### Issue: "Host key verification failed"

**Cause:** GitHub's SSH host key is not in ArgoCD's `known_hosts`.

**Solution:** Add GitHub's SSH host keys to ArgoCD:

```bash
kubectl patch configmap argocd-ssh-known-hosts-cm -n argocd --type merge -p '
data:
  ssh_known_hosts: |
    github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CTZJVAK+7KDwzJe7q36rW7R5s3bSjJShN2aXQRJ0KHNxU3CQGpzSQIgLuuNqW8rQSQ5qv+3vqQmCPH0dGPDFLNZBqm1EgD0xSJi0b70S3e8xnPLHjIh0tQ6NTGa6v9OJqgPkqSLs2xKV9OBHVFfC8Qjw6V2V0jZjG1c+bm9X3V7j5yC1X1qPy7T6xN3xF2c1bw2m3YjE3vZq0xjy7rJX3m3yR0h0t6qE8yV7xZ2xH9m3YH9w3h0xH6qE3qH3vI7qECXM3pYdwLqZ8yb5k/g=
    github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
    github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
'

# Restart ArgoCD pods to pick up the change
kubectl rollout restart deployment -n argocd
```

---

### Issue: "Permission denied (publickey)"

**Cause:** SSH Deploy Key not added to GitHub or incorrect key format.

**Solution:**

1. Verify the public key format:
   ```bash
   cat k8s/gitops/ssh/argocd.pub
   ```
   Should start with: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA...`

2. Re-add to GitHub: https://github.com/ariel99gf/homelab/settings/keys

3. Test connection from ArgoCD:
   ```bash
   kubectl exec -n argocd deployment/argocd-repo-server -- \
     ssh -T git@github.com
   ```

---

### Issue: Applications stuck in "Progressing"

**Cause:** Resource quota limits, image pull errors, or dependency issues.

**Solution:**

```bash
# Check application sync status details
kubectl get application <app-name> -n argocd -o yaml | grep -A 20 status

# Check pod events
kubectl get events -n <app-namespace> --sort-by='.lastTimestamp' | tail -20

# Check pod logs
kubectl logs -n <app-namespace> <pod-name>
```

---

### Issue: OCI Throttling Still Occurring

**Cause:** ArgoCD is still using HTTPS instead of SSH.

**Solution:**

```bash
# Verify the repository URL is SSH
kubectl get application homelab-apps-root -n argocd -o jsonpath='{.spec.source.repoURL}'

# Should output: git@github.com:ariel99gf/homelab.git

# If still HTTPS, re-apply apps-root.yaml
kubectl apply -f k8s/gitops/apps-root.yaml
```

---

## Success Metrics

After completing all validation steps, confirm:

| Metric                        | Target           | Command to Verify                                      |
|-------------------------------|------------------|--------------------------------------------------------|
| All apps synced               | 100%             | `kubectl get apps -n argocd`                           |
| All apps healthy              | 100%             | `kubectl get apps -n argocd`                           |
| SSH authentication working    | No errors        | `kubectl logs -n argocd deploy/argocd-repo-server`     |
| GitHub throttling eliminated  | No rate limit    | Check ArgoCD logs for "rate limit" or "403" errors     |
| Self-heal operational         | <60s recovery    | Test drift detection (step 8)                          |
| Target branch correct         | `develop`        | `kubectl get app homelab-apps-root -n argocd -o yaml`  |

---

## Final Validation Command

Run this comprehensive check:

```bash
#!/usr/bin/env bash
# final-validation.sh

echo "=== Phase 6 Validation Report ==="
echo ""

echo "1. Repository Secret:"
kubectl get secret argocd-repo-homelab -n argocd &>/dev/null && echo "✅ Exists" || echo "❌ Missing"

echo ""
echo "2. App-of-Apps Configuration:"
REPO_URL=$(kubectl get application homelab-apps-root -n argocd -o jsonpath='{.spec.source.repoURL}')
TARGET_REV=$(kubectl get application homelab-apps-root -n argocd -o jsonpath='{.spec.source.targetRevision}')
echo "   Repo URL: $REPO_URL"
echo "   Target Branch: $TARGET_REV"

[[ "$REPO_URL" == "git@github.com:ariel99gf/homelab.git" ]] && echo "   ✅ SSH URL" || echo "   ❌ Still HTTPS"
[[ "$TARGET_REV" == "develop" ]] && echo "   ✅ Develop branch" || echo "   ❌ Wrong branch"

echo ""
echo "3. Application Sync Status:"
kubectl get applications -n argocd -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status

echo ""
echo "4. ArgoCD Repo Server Health:"
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-repo-server -o jsonpath='{.items[0].status.phase}' | grep Running &>/dev/null && echo "✅ Running" || echo "❌ Not Running"

echo ""
echo "=== End of Report ==="
```

Save this script and run:

```bash
chmod +x final-validation.sh
./final-validation.sh
```

---

## Next Steps (After Validation)

1. ✅ Mark Phase 6 as complete in `.opencode/plan.md`
2. 📝 Document any issues encountered in `docs/troubleshooting.md`
3. 🔄 Schedule Helm migration (optional, see `HELM_MIGRATION_PROPOSAL.md`)
4. 🔐 Set calendar reminder for SSH key rotation (1 year)
5. 📊 Monitor ArgoCD resource usage for 7 days (ensure Raspberry Pi constraints)

---

**Author:** Claude (Tech Lead)
**Date:** 2026-01-23
**Phase:** 6 - Advanced GitOps & App Lifecycle
