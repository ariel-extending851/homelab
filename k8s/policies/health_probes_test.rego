package main

# Test fixtures for health_probes.rego.
# Run via: conftest verify --policy k8s/policies/
# Helpers live in test_helpers.rego (shared across policy test files).

hp_deployment_with_probes := {
  "kind": "Deployment",
  "metadata": {"name": "ok"},
  "spec": {"template": {"spec": {"containers": [fully_compliant_container]}}},
}

hp_container_no_readiness := {
  "name": "c1",
  "livenessProbe": {"httpGet": {"path": "/", "port": 80}},
  "resources": {
    "limits": {"cpu": "100m", "memory": "128Mi"},
    "requests": {"cpu": "50m", "memory": "64Mi"},
  },
  "securityContext": {"allowPrivilegeEscalation": false},
}

hp_deployment_no_readiness := {
  "kind": "Deployment",
  "metadata": {"name": "bad"},
  "spec": {"template": {"spec": {"containers": [hp_container_no_readiness]}}},
}

hp_container_no_liveness := {
  "name": "c1",
  "readinessProbe": {"httpGet": {"path": "/", "port": 80}},
  "resources": {
    "limits": {"cpu": "100m", "memory": "128Mi"},
    "requests": {"cpu": "50m", "memory": "64Mi"},
  },
  "securityContext": {"allowPrivilegeEscalation": false},
}

hp_deployment_only_readiness := {
  "kind": "Deployment",
  "metadata": {"name": "warnable"},
  "spec": {"template": {"spec": {"containers": [hp_container_no_liveness]}}},
}

hp_daemonset_no_readiness := {
  "kind": "DaemonSet",
  "metadata": {"name": "bad-ds"},
  "spec": {"template": {"spec": {"containers": [hp_container_no_readiness]}}},
}

# ── deny rules ──────────────────────────────────────────────────────────────

test_deployment_with_probes_no_probe_denies {
  not has_message(deny, "readinessProbe") with input as hp_deployment_with_probes
}

test_deployment_missing_readiness_denied {
  has_message(deny, "readinessProbe") with input as hp_deployment_no_readiness
}

test_deployment_missing_readiness_message_names_resource {
  some msg
  deny[msg] with input as hp_deployment_no_readiness
  contains(msg, "bad")
  contains(msg, "readinessProbe")
}

test_daemonset_missing_readiness_denied {
  has_message(deny, "readinessProbe") with input as hp_daemonset_no_readiness
}

# ── warn rules ──────────────────────────────────────────────────────────────

test_deployment_missing_liveness_warns {
  has_message(warn, "livenessProbe") with input as hp_deployment_only_readiness
}

test_deployment_with_full_probes_no_warn {
  not has_message(warn, "livenessProbe") with input as hp_deployment_with_probes
}
