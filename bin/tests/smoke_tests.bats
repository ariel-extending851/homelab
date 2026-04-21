#!/usr/bin/env bats
# Unit tests for bin/smoke-test.sh.
# Mocks kubectl via PATH prepend so no real cluster is required.
#
# Run locally: bats bin/tests/smoke_tests.bats
# CI: covered by make test-shell

SMOKE_SCRIPT="${BATS_TEST_DIRNAME}/../smoke-test.sh"

setup() {
  MOCK_DIR="$(mktemp -d)"
  export PATH="${MOCK_DIR}:${PATH}"
  export KUBECONFIG="/dev/null"
}

teardown() {
  rm -rf "${MOCK_DIR}"
}

# ── helper ────────────────────────────────────────────────────────────────────

_write_kubectl() {
  cat > "${MOCK_DIR}/kubectl"
  chmod +x "${MOCK_DIR}/kubectl"
}

# ── 1. Cluster reachability ───────────────────────────────────────────────────

@test "smoke: exits 0 when cluster is reachable and all checks pass" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    echo "Kubernetes control plane is running"
    exit 0
    ;;
  "get applications -n argocd -o json")
    echo '{"items":[{"metadata":{"name":"app1"},"status":{"sync":{"status":"Synced"},"health":{"status":"Healthy"}}}]}'
    exit 0
    ;;
  "get pods -A --no-headers")
    echo "default   pod-ok   1/1   Running   0   1d"
    exit 0
    ;;
  "get namespace argocd"|"get namespace monitoring"|"get namespace adguard")
    echo "NAME    STATUS   AGE"
    exit 0
    ;;
  get\ deployment\ argocd-repo-server\ -n\ argocd\ -o\ *)
    printf "1"
    exit 0
    ;;
  get\ deployment\ *\ -o\ jsonpath={.status.readyReplicas})
    printf "1"
    exit 0
    ;;
  get\ deployment\ *\ -o\ jsonpath={.spec.replicas})
    printf "1"
    exit 0
    ;;
  "get pvc -A --no-headers")
    # Expected kubectl columns: NAMESPACE STATUS NAME
    echo "media Bound pvc-media"
    exit 0
    ;;
  "get statefulset -A --no-headers")
    # Empty output means no StatefulSets to validate.
    exit 0
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 0 ]
  [[ "$output" =~ "All smoke tests passed" ]]
}

@test "smoke: exits 1 when cluster is unreachable" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    exit 1
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "unreachable" ]]
}

# ── 2. ArgoCD sync status ─────────────────────────────────────────────────────

@test "smoke: detects OutOfSync ArgoCD application" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    exit 0
    ;;
  "get applications -n argocd -o json")
    echo '{"items":[{"metadata":{"name":"my-app"},"status":{"sync":{"status":"OutOfSync"},"health":{"status":"Healthy"}}}]}'
    exit 0
    ;;
  "get pods -A --no-headers")
    exit 0
    ;;
  "get namespace argocd"|"get namespace monitoring"|"get namespace adguard")
    exit 0
    ;;
  "get deployment argocd-repo-server -n argocd -o jsonpath={.status.readyReplicas}")
    printf "1"
    exit 0
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Not Synced" ]]
}

# ── 3. ArgoCD health status ───────────────────────────────────────────────────

@test "smoke: detects Degraded ArgoCD application" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    exit 0
    ;;
  "get applications -n argocd -o json")
    echo '{"items":[{"metadata":{"name":"my-app"},"status":{"sync":{"status":"Synced"},"health":{"status":"Degraded"}}}]}'
    exit 0
    ;;
  "get pods -A --no-headers")
    exit 0
    ;;
  "get namespace argocd"|"get namespace monitoring"|"get namespace adguard")
    exit 0
    ;;
  "get deployment argocd-repo-server -n argocd -o jsonpath={.status.readyReplicas}")
    printf "1"
    exit 0
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Not Healthy" ]]
}

# ── 4. Pod failure detection ──────────────────────────────────────────────────

@test "smoke: detects CrashLoopBackOff pods" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    exit 0
    ;;
  "get applications -n argocd -o json")
    echo '{"items":[{"metadata":{"name":"app1"},"status":{"sync":{"status":"Synced"},"health":{"status":"Healthy"}}}]}'
    exit 0
    ;;
  "get pods -A --no-headers")
    echo "media   broken-pod   0/1   CrashLoopBackOff   5   10m"
    exit 0
    ;;
  "get namespace argocd"|"get namespace monitoring"|"get namespace adguard")
    exit 0
    ;;
  "get deployment argocd-repo-server -n argocd -o jsonpath={.status.readyReplicas}")
    printf "1"
    exit 0
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "failure state" ]]
}

# ── 5. Namespace presence ─────────────────────────────────────────────────────

@test "smoke: detects missing required namespace" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    exit 0
    ;;
  "get applications -n argocd -o json")
    echo '{"items":[{"metadata":{"name":"app1"},"status":{"sync":{"status":"Synced"},"health":{"status":"Healthy"}}}]}'
    exit 0
    ;;
  "get pods -A --no-headers")
    exit 0
    ;;
  "get namespace argocd")
    exit 0
    ;;
  "get namespace monitoring")
    exit 1
    ;;
  "get namespace adguard")
    exit 0
    ;;
  "get deployment argocd-repo-server -n argocd -o jsonpath={.status.readyReplicas}")
    printf "1"
    exit 0
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "missing" ]]
}

# ── 6. ArgoCD repo-server readiness ──────────────────────────────────────────

@test "smoke: detects argocd-repo-server with no ready replicas" {
  _write_kubectl << 'EOF'
#!/bin/bash
case "$*" in
  "cluster-info --request-timeout=10s")
    exit 0
    ;;
  "get applications -n argocd -o json")
    echo '{"items":[{"metadata":{"name":"app1"},"status":{"sync":{"status":"Synced"},"health":{"status":"Healthy"}}}]}'
    exit 0
    ;;
  "get pods -A --no-headers")
    exit 0
    ;;
  "get namespace argocd"|"get namespace monitoring"|"get namespace adguard")
    exit 0
    ;;
  "get deployment argocd-repo-server -n argocd -o jsonpath={.status.readyReplicas}")
    printf "0"
    exit 0
    ;;
esac
exit 0
EOF
  run bash "${SMOKE_SCRIPT}"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "no ready replicas" ]]
}
