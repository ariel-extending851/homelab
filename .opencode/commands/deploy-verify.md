---
description: Verify deployment health after ArgoCD sync completes.
---

# Instructions

Post-deployment health verification. Provides AWS CodeDeploy lifecycle hooks equivalent for homelab deployments.

## 1. Detect Recent Deployments

Auto-detect recent deployments from git log:

```bash
# Get last 5 commits to identify what was deployed
RECENT_COMMITS=$(git log --oneline -5 --grep="feat\|fix" --pretty=format:"%h %s")

echo "📊 Recent deployments detected:"
echo "$RECENT_COMMITS"
echo ""
```

If user wants to verify specific app, they can provide app name as argument.

## 2. Query ArgoCD Application Status

For each application (or specified app), check ArgoCD sync and health status:

```bash
APP_NAME="${1:-homelab-apps-root}"  # Default to root app if not specified

echo "🔍 Checking ArgoCD status for: $APP_NAME"
echo ""

# Get sync status
SYNC_STATUS=$(kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)

# Get health status
HEALTH_STATUS=$(kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null)

# Get last sync time
LAST_SYNC=$(kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.operationState.finishedAt}' 2>/dev/null)

# Get current revision
REVISION=$(kubectl get application $APP_NAME -n argocd -o jsonpath='{.status.sync.revision}' 2>/dev/null)

if [ -z "$SYNC_STATUS" ]; then
    echo "❌ Application not found in ArgoCD"
    exit 1
fi
```

## 3. Check Kubernetes Pod Status

If application is a root app (manages other apps), check all child apps:

```bash
if [ "$APP_NAME" == "homelab-apps-root" ]; then
    echo "📦 Checking all managed applications..."
    kubectl get applications -n argocd -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
else
    # For specific app, check pod status
    NAMESPACE=$(kubectl get application $APP_NAME -n argocd -o jsonpath='{.spec.destination.namespace}')
    
    echo "📦 Checking pods in namespace: $NAMESPACE"
    kubectl get pods -n $NAMESPACE -o wide
    
    # Check for crashlooping or pending pods
    UNHEALTHY_PODS=$(kubectl get pods -n $NAMESPACE -o json | jq -r '.items[] | select(.status.phase != "Running" and .status.phase != "Succeeded") | .metadata.name')
    
    if [ -n "$UNHEALTHY_PODS" ]; then
        echo ""
        echo "⚠️  Unhealthy pods detected:"
        echo "$UNHEALTHY_PODS"
    fi
fi
```

## 4. Generate Health Report

Create formatted report with deployment status:

```bash
REPORT_FILE=".opencode/last-deploy-verify.md"

cat > $REPORT_FILE <<EOF
# Deployment Verification Report

**Date:** $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Application:** $APP_NAME

## ArgoCD Status

| Metric | Value |
|--------|-------|
| Sync Status | $SYNC_STATUS |
| Health Status | $HEALTH_STATUS |
| Last Sync | $LAST_SYNC |
| Current Revision | $REVISION |

## Kubernetes Status

\`\`\`
$(kubectl get pods -n ${NAMESPACE:-argocd} -o wide)
\`\`\`

## Verification Result

EOF

# Determine overall status
if [ "$SYNC_STATUS" == "Synced" ] && [ "$HEALTH_STATUS" == "Healthy" ]; then
    echo "✅ **PASS** - Deployment is healthy" >> $REPORT_FILE
    echo ""
    echo "✅ Deployment verification PASSED"
    echo "Report saved to: $REPORT_FILE"
    exit 0
else
    echo "❌ **FAIL** - Deployment has issues" >> $REPORT_FILE
    echo ""
    echo "❌ Deployment verification FAILED"
    echo "Sync: $SYNC_STATUS | Health: $HEALTH_STATUS"
    echo "Report saved to: $REPORT_FILE"
    exit 1
fi
```

## 5. Optional Health Endpoint Checks (Future Enhancement)

*Note: HTTP health endpoint checks are not implemented in initial version. Can be added later if needed.*

Potential endpoints to check:
- ***: `http://***.media.svc:8096/health`
- Grafana: `http://grafana.monitoring.svc:3000/api/health`
- Prometheus: `http://prometheus.monitoring.svc:9090/-/healthy`

---

**Usage:**

```bash
/deploy-verify                  # Check homelab-apps-root (all apps)
/deploy-verify ***         # Check specific app
/deploy-verify prometheus       # Check monitoring stack
```

**Requirements:**
- kubectl access to argocd namespace
- jq for JSON parsing
- Write access to `.opencode/last-deploy-verify.md`

**Integration Points:**
- Can be run manually after deployments
- Can be integrated into CI/CD pipeline
- Results saved for audit trail
