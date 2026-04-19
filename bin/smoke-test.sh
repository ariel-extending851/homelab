#!/usr/bin/env bash
# Post-deploy smoke test — verifies cluster health after make deploy.
# Usage: KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml bin/smoke-test.sh
set -euo pipefail

KUBECONFIG="${KUBECONFIG:-/tmp/k3s-homelab-kubeconfig.yaml}"
export KUBECONFIG
ARGOCD_NS="${ARGOCD_NAMESPACE:-argocd}"

FAILED=0
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; FAILED=$((FAILED + 1)); }

echo "🔍 Post-deploy smoke tests (KUBECONFIG=${KUBECONFIG})"
echo ""

# ── 1. Cluster reachability ───────────────────────────────────────────────────
echo "▶ Cluster connectivity"
if kubectl cluster-info --request-timeout=10s >/dev/null 2>&1; then
  pass "API server reachable"
else
  fail "API server unreachable — check KUBECONFIG=${KUBECONFIG}"
  echo "   Cannot continue without API access." && exit 1
fi

# ── 2. ArgoCD apps: all Synced ────────────────────────────────────────────────
echo "▶ ArgoCD sync status"
APPS_JSON=$(kubectl get applications -n "$ARGOCD_NS" -o json 2>/dev/null || echo "")
if [ -z "$APPS_JSON" ] || [ "$(echo "$APPS_JSON" | jq '.items | length')" -eq 0 ]; then
  fail "No ArgoCD applications found (namespace: $ARGOCD_NS)"
else
  NOT_SYNCED=$(echo "$APPS_JSON" \
    | jq -r '[.items[] | select(.status.sync.status != "Synced")] | map(.metadata.name) | join(", ")')
  NOT_HEALTHY=$(echo "$APPS_JSON" \
    | jq -r '[.items[] | select(.status.health.status != "Healthy")] | map(.metadata.name) | join(", ")')

  if [ -z "$NOT_SYNCED" ]; then
    pass "All ArgoCD apps are Synced"
  else
    fail "Not Synced: ${NOT_SYNCED}"
  fi

  if [ -z "$NOT_HEALTHY" ]; then
    pass "All ArgoCD apps are Healthy"
  else
    fail "Not Healthy: ${NOT_HEALTHY}"
  fi
fi

# ── 3. No pods in terminal failure states ─────────────────────────────────────
echo "▶ Pod health (all namespaces)"
FAILED_PODS=$(kubectl get pods -A --no-headers 2>/dev/null \
  | awk '$4 ~ /CrashLoopBackOff|OOMKilled|ImagePullBackOff|ErrImagePull|Error/ {
      printf "    %s/%s (%s)\n", $1, $2, $4
    }')

if [ -z "$FAILED_PODS" ]; then
  pass "No pods in failure state"
else
  fail "Pods in failure state:"
  echo "$FAILED_PODS"
fi

# ── 4. Key namespaces present ─────────────────────────────────────────────────
echo "▶ Namespace presence"
for ns in argocd monitoring adguard; do
  if kubectl get namespace "$ns" >/dev/null 2>&1; then
    pass "Namespace '${ns}' exists"
  else
    fail "Namespace '${ns}' missing"
  fi
done

# ── 5. ArgoCD repo-server reachable (CMP sidecar health) ─────────────────────
echo "▶ ArgoCD repo-server pod"
REPO_READY=$(kubectl get deployment argocd-repo-server -n "$ARGOCD_NS" \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "${REPO_READY:-0}" -ge 1 ]; then
  pass "argocd-repo-server has ${REPO_READY} ready replica(s)"
else
  fail "argocd-repo-server has no ready replicas (SOPS CMP may be broken)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "✅ All smoke tests passed — cluster is healthy."
else
  echo "❌ ${FAILED} smoke test(s) FAILED — investigate before declaring success."
  exit 1
fi
