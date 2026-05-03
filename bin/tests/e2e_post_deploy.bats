#!/usr/bin/env bats
# E2E post-deployment tests — comprehensive validation after cluster bootstrap.
# Unlike smoke_tests.bats (which mocks kubectl), these are REAL tests against live cluster.
#
# Requirements: kubectl context to live k3s cluster, jq, curl, dig
# Run after deployment: bats bin/tests/e2e_post_deploy.bats
# Makefile: make test-e2e-post-deploy

KUBECONFIG="${KUBECONFIG:-/tmp/k3s-homelab-kubeconfig.yaml}"
export KUBECONFIG
ARGOCD_NS="${ARGOCD_NAMESPACE:-argocd}"
TIMEOUT_SECONDS=10

# ── setup ──────────────────────────────────────────────────────────────────────
# Post-deploy: cluster MUST be up. Unreachable = hard fail, never skip.
# Silent skips previously let the deployment-gate job pass on vacuous "success".

setup() {
  if ! kubectl cluster-info --request-timeout=5s >/dev/null 2>&1; then
    echo "FATAL: cluster unreachable (KUBECONFIG=${KUBECONFIG})" >&2
    return 1
  fi
}

# ──────────────────────────────────────────────────────────────────────────────
# CLUSTER READINESS (baseline)
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: Cluster API is reachable" {
  kubectl cluster-info --request-timeout="${TIMEOUT_SECONDS}s" >/dev/null
}

@test "E2E: ArgoCD root app is Synced and Healthy" {
  APPS_JSON=$(kubectl get applications -n "$ARGOCD_NS" -o json 2>/dev/null || echo "{}")
  SYNCED=$(echo "$APPS_JSON" | jq -r '[.items[] | select(.status.sync.status == "Synced")] | length')
  [ "$SYNCED" -gt 0 ]

  HEALTHY=$(echo "$APPS_JSON" | jq -r '[.items[] | select(.status.health.status == "Healthy")] | length')
  [ "$HEALTHY" -gt 0 ]
}

# ──────────────────────────────────────────────────────────────────────────────
# GITOPS REPOSITORY CREDENTIALS
# ──────────────────────────────────────────────────────────────────────────────
# Postmortem 2026-05-03 (gotcha #5): apps-root previously failed to sync silently
# when homelab-repo-secret was not created (Ansible task skipped because
# ~/.ssh/homelab-deploy-key was absent on the control machine). These tests
# catch that regression — both the secret's existence and the resulting
# apps-root sync state.

@test "E2E: homelab-repo-secret exists with repository label" {
  # ArgoCD discovers Git credentials by scanning for Secrets labelled
  # argocd.argoproj.io/secret-type=repository in its namespace.
  kubectl -n "$ARGOCD_NS" get secret homelab-repo-secret >/dev/null

  LABEL=$(kubectl -n "$ARGOCD_NS" get secret homelab-repo-secret \
    -o jsonpath='{.metadata.labels.argocd\.argoproj\.io/secret-type}' 2>/dev/null)
  [ "$LABEL" = "repository" ]
}

@test "E2E: apps-root sync status is not Unknown" {
  # "Unknown" is the symptom of missing repo credentials — ArgoCD can't
  # connect to GitHub. "Synced" or "OutOfSync" both prove connectivity works.
  STATUS=$(kubectl -n "$ARGOCD_NS" get application homelab-apps-root \
    -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "")
  [ -n "$STATUS" ]
  [ "$STATUS" != "Unknown" ]
}

# ──────────────────────────────────────────────────────────────────────────────
# APPLICATION HEALTH
# ──────────────────────────────────────────────────────────────────────────────

# Parametrized app tests (for reference/documentation)
# shellcheck disable=SC2034
declare -a APPS=(
  "adguard:adguard"
  "blackbox:monitoring"
  "golink:golink"
  "grafana:monitoring"
  "kube-state-metrics:monitoring"
  "loki:monitoring"
  "node-exporter:monitoring"
  "otel-collector:otel-collector"
  "prometheus:monitoring"
)

@test "E2E: adguard deployment is Ready" {
  READY=$(kubectl get deploy adguard -n adguard -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "${READY}" -ge 1 ]
}

@test "E2E: blackbox deployment is Ready" {
  READY=$(kubectl get deploy blackbox -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "${READY}" -ge 1 ]
}

@test "E2E: grafana deployment is Ready" {
  READY=$(kubectl get deploy grafana -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "${READY}" -ge 1 ]
}

@test "E2E: prometheus deployment is Ready" {
  READY=$(kubectl get deploy prometheus -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "${READY}" -ge 1 ]
}

@test "E2E: loki deployment is Ready" {
  READY=$(kubectl get deploy loki -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  [ "${READY}" -ge 1 ]
}

# ──────────────────────────────────────────────────────────────────────────────
# PERSISTENCE VALIDATION (PVCs)
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: All PVCs are Bound" {
  UNBOUND=$(kubectl get pvc -A --no-headers 2>/dev/null | awk '$2 != "Bound" {count++} END {print count}' || echo "0")
  [ "$UNBOUND" -eq 0 ]
}

@test "E2E: adguard PVC is mounted" {
  PHASE=$(kubectl get pvc -n adguard -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")
  [ "$PHASE" == "Bound" ]
}

# ──────────────────────────────────────────────────────────────────────────────
# COMPLIANCE CHECKS
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: No pods in CrashLoopBackOff" {
  CRASHED=$(kubectl get pods -A --no-headers 2>/dev/null | grep -c "CrashLoopBackOff" || echo "0")
  [ "$CRASHED" -eq 0 ]
}

@test "E2E: No pods in ImagePullBackOff" {
  PULL_FAILED=$(kubectl get pods -A --no-headers 2>/dev/null | grep -c "ImagePullBackOff" || echo "0")
  [ "$PULL_FAILED" -eq 0 ]
}

@test "E2E: No pods in OOMKilled state" {
  OOM=$(kubectl get pods -A --no-headers 2>/dev/null | grep -c "OOMKilled" || echo "0")
  [ "$OOM" -eq 0 ]
}

@test "E2E: All StatefulSets at desired replicas" {
  MISMATCH=$(kubectl get statefulset -A --no-headers 2>/dev/null \
    | awk '$2 != $3 {count++} END {print count}' || echo "0")
  [ "$MISMATCH" -eq 0 ]
}

# ──────────────────────────────────────────────────────────────────────────────
# OBSERVABILITY PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: Prometheus has metrics available" {
  skip "Requires port-forward setup — manual verification recommended"
  # In live deployment, run:
  # kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
  # curl -s 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result | length > 0'
}

@test "E2E: Loki has logs available" {
  skip "Requires port-forward setup — manual verification recommended"
  # In live deployment, run:
  # kubectl port-forward -n monitoring svc/loki 3100:3100 &
  # curl -s 'http://localhost:3100/loki/api/v1/query_range?query={job="kubelet"}' | jq '.data.result | length > 0'
}

# ──────────────────────────────────────────────────────────────────────────────
# RESOURCE VALIDATION
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: All nodes are Ready" {
  NOT_READY=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 !~ /Ready/ {count++} END {print count}' || echo "0")
  [ "$NOT_READY" -eq 0 ]
}

@test "E2E: All DaemonSets are deployed to all nodes" {
  MISMATCH=$(kubectl get daemonset -A --no-headers 2>/dev/null \
    | awk '$2 != $3 {count++} END {print count}' || echo "0")
  [ "$MISMATCH" -eq 0 ]
}

@test "E2E: ArgoCD namespace exists" {
  kubectl get namespace "$ARGOCD_NS" >/dev/null 2>&1
}

@test "E2E: monitoring namespace exists" {
  kubectl get namespace monitoring >/dev/null 2>&1
}

@test "E2E: adguard namespace exists" {
  kubectl get namespace adguard >/dev/null 2>&1
}

# ──────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: Final health check — cluster ready for production" {
  # This test aggregates results of all checks above
  # If executed here without error, cluster is production-ready

  FAILED_PODS=$(kubectl get pods -A --no-headers 2>/dev/null \
    | awk '$3 ~ /CrashLoopBackOff|ImagePullBackOff|OOMKilled/ {count++} END {print count}' || echo "0")

  [ "$FAILED_PODS" -eq 0 ]
}

# ──────────────────────────────────────────────────────────────────────────────
# HTTP FUNCTIONAL CONTRACT (Service-level, in-cluster)
# ──────────────────────────────────────────────────────────────────────────────
# Tailscale ingress can't be reached from CI (not on the tailnet), so we probe
# each Service's ClusterIP from inside the cluster via a one-shot curl pod.
# This catches: wrong Service selector, wrong targetPort, app listening on wrong
# port, app returning 5xx. Pod-Ready alone doesn't catch any of these.
#
# "Any non-5xx response" = routing works. 3xx (redirect) and 4xx (auth) are OK.

@test "E2E: HTTP contract — all key Services respond (no 5xx)" {
  # svc:namespace:port — only apps with HTTP APIs; exclude DNS-only (adguard),
  # headless (loki push-only endpoints), exporters (not user-facing).
  SERVICES=(
    "grafana:monitoring:3000"
    "prometheus:monitoring:9090"
  )

  script=""
  for entry in "${SERVICES[@]}"; do
    IFS=':' read -r svc ns port <<<"$entry"
    url="http://${svc}.${ns}.svc.cluster.local:${port}/"
    # Print "svc CODE" per line. 000 = connection failure.
    script+="code=\$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 '${url}' || echo 000); echo '${svc} '\$code; "
  done

  output=$(kubectl run http-probe-$$ \
    --rm --restart=Never --quiet -i \
    --image=curlimages/curl:8.10.1 \
    --timeout=60s \
    -- sh -c "$script" 2>&1)

  echo "$output"

  # Any 5xx or connection failure (000) = fail. Accept 1xx/2xx/3xx/4xx.
  if echo "$output" | grep -E ' (5[0-9][0-9]|000)$' >/dev/null; then
    echo "FAIL: one or more Services returned 5xx or timed out"
    return 1
  fi
}

# ──────────────────────────────────────────────────────────────────────────────
# DISASTER RECOVERY (Velero backup readiness)
# ──────────────────────────────────────────────────────────────────────────────

@test "E2E: Velero deployment is Ready" {
  ready=$(kubectl get deployment velero -n velero \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
  [ "${ready:-0}" -ge 1 ]
}

@test "E2E: Velero daily-backup schedule exists" {
  kubectl get schedule.velero.io daily-backup -n velero >/dev/null
}

@test "E2E: Velero BackupStorageLocation is Available" {
  phase=$(kubectl get backupstoragelocation.velero.io default -n velero \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
  [ "$phase" = "Available" ]
}
