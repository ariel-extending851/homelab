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

# ── 6. Application deployments ready (17 apps) ─────────────────────────────────
echo "▶ Application deployment health (17 apps)"
APPS=(
  "adguard:adguard"
  "blackbox:monitoring"
  "***:adguard"
  "golink:golink"
  "grafana:monitoring"
  "***:***"
  "kube-state-metrics:monitoring"
  "loki:monitoring"
  "node-exporter:monitoring"
  "otel-collector:otel-collector"
  "prometheus:monitoring"
  "***:media"
  "***:media"
  "***:media"
  "searxng:searxng"
  "***:media"
)

APPS_FAILED=0
for app_ns in "${APPS[@]}"; do
  IFS=':' read -r app ns <<< "$app_ns"
  READY=$(kubectl get deployment "$app" -n "$ns" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  DESIRED=$(kubectl get deployment "$app" -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")

  if [ "${READY:-0}" -ge 1 ] && [ "${READY:-0}" -eq "${DESIRED}" ]; then
    pass "$app ($ns): ${READY}/${DESIRED} replicas ready"
  else
    fail "$app ($ns): ${READY:-0}/${DESIRED} replicas (expected ${DESIRED})"
    APPS_FAILED=$((APPS_FAILED + 1))
  fi
done

# ── 7. PVC validation (persistent volumes) ─────────────────────────────────────
echo "▶ Persistent Volume Claims (PVCs)"
UNBOUND_PVCS=$(kubectl get pvc -A --no-headers 2>/dev/null \
  | awk '$2 != "Bound" {printf "    %s/%s (%s)\n", $1, $2, $3}' \
  || echo "")

if [ -z "$UNBOUND_PVCS" ]; then
  TOTAL_PVCS=$(kubectl get pvc -A --no-headers 2>/dev/null | wc -l)
  pass "All ${TOTAL_PVCS} PVCs are Bound"
else
  fail "PVCs not Bound:"
  echo "$UNBOUND_PVCS"
  FAILED=$((FAILED + 1))
fi

# ── 8. Prometheus connectivity (observability) ──────────────────────────────────
echo "▶ Observability stack (Prometheus + Loki)"
PROM_READY=$(kubectl get deployment prometheus -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
LOKI_READY=$(kubectl get deployment loki -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")

if [ "${PROM_READY:-0}" -ge 1 ]; then
  pass "Prometheus: ${PROM_READY} replica(s) ready"
else
  fail "Prometheus: no ready replicas"
  FAILED=$((FAILED + 1))
fi

if [ "${LOKI_READY:-0}" -ge 1 ]; then
  pass "Loki: ${LOKI_READY} replica(s) ready"
else
  fail "Loki: no ready replicas"
  FAILED=$((FAILED + 1))
fi

# ── 9. StatefulSets at desired replica count ────────────────────────────────────
echo "▶ StatefulSet replicas"
STATEFULSET_MISMATCH=$(kubectl get statefulset -A --no-headers 2>/dev/null \
  | awk '$2 != $3 {printf "    %s/%s: %s/%s\n", $1, $2, $2, $3}' \
  || echo "")

if [ -z "$STATEFULSET_MISMATCH" ]; then
  TOTAL_STS=$(kubectl get statefulset -A --no-headers 2>/dev/null | wc -l)
  if [ "$TOTAL_STS" -gt 0 ]; then
    pass "All ${TOTAL_STS} StatefulSets match desired replicas"
  else
    pass "No StatefulSets to validate"
  fi
else
  fail "StatefulSets replicas mismatch:"
  echo "$STATEFULSET_MISMATCH"
  FAILED=$((FAILED + 1))
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [ "$FAILED" -eq 0 ] && [ "$APPS_FAILED" -eq 0 ]; then
  echo "✅ All smoke tests passed — cluster is production-ready."
  exit 0
elif [ "$FAILED" -eq 0 ] && [ "$APPS_FAILED" -lt 3 ]; then
  echo "⚠️  Minor issues (${APPS_FAILED} app(s)) — investigate before release."
  exit 2
else
  echo "❌ ${FAILED} smoke test(s) FAILED (${APPS_FAILED} app(s)) — ROLLBACK recommended."
  exit 1
fi
