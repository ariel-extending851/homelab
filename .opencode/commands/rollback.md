---
description: Rollback an ArgoCD application to a previous healthy revision.
---

# Instructions

Manual rollback wrapper for ArgoCD applications. Provides AWS CodeDeploy-style rollback capabilities for homelab scale.

## 1. Pre-Flight Check

* Verify ArgoCD is accessible: `kubectl get pods -n argocd`
* If ArgoCD pods are not running, exit with error

## 2. List Available Applications

If no application name provided, list all ArgoCD applications:

```bash
kubectl get applications -n argocd -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
```

User should specify which application to rollback.

## 3. Get Revision History

For the specified application, retrieve deployment history:

```bash
APP_NAME="<application-name>"

# Get current revision
kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.sync.revision}'

# Get history (last 10 revisions)
kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.history}' | jq -r '.[] | "\(.id) | \(.deployedAt) | \(.source.targetRevision) | Sync: \(.source.repoURL)"' | tail -10
```

## 4. Identify Last Healthy Revision

Analyze history to find the last revision with healthy status:

```bash
# Show sync history with health status
kubectl get application $APP_NAME -n argocd -o json | jq -r '.status.history[] | select(.deployedAt != null) | "\(.id) | \(.deployedAt) | Health: \(.source.targetRevision)"' | tail -5
```

Present options to user with revision IDs.

## 5. Execute Rollback

**CRITICAL:** Require user confirmation before rollback.

```bash
REVISION_ID="<user-selected-revision>"

echo "⚠️  ROLLBACK CONFIRMATION"
echo "Application: $APP_NAME"
echo "Current Revision: $(kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.sync.revision}')"
echo "Target Revision: $REVISION_ID"
echo ""
read -p "Type application name to confirm rollback: " CONFIRM

if [ "$CONFIRM" != "$APP_NAME" ]; then
    echo "❌ Rollback cancelled"
    exit 1
fi

# Perform rollback using ArgoCD CLI or kubectl patch
argocd app rollback $APP_NAME $REVISION_ID --prune
```

## 6. Verify Rollback

After rollback execution:

```bash
# Wait for sync to complete
kubectl wait --for=condition=Synced application/$APP_NAME -n argocd --timeout=300s

# Check health status
kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.health.status}'

# Show current revision
echo "Rolled back to revision: $(kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.sync.revision}')"
```

## 7. Document Incident

Update `.opencode/memory.md` with rollback details:

```markdown
### Rollback: <application-name> - <date>

**Reason:** <user-provided reason>
**From Revision:** <old-revision>
**To Revision:** <new-revision>
**Outcome:** <success/failure>
**Duration:** <time-taken>
```

---

**Usage:**

```bash
/rollback                      # List applications
/rollback ***             # Rollback specific app
/rollback homelab-apps-root    # Rollback root app (dangerous!)
```

**Requirements:**
- ArgoCD CLI (`argocd`) installed
- kubectl access to argocd namespace
- Write access to `.opencode/memory.md`
