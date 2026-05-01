package main

# Test fixtures for security_context.rego. Helpers in test_helpers.rego.

sc_overhead := {
  "readinessProbe": {"httpGet": {"path": "/", "port": 80}},
  "livenessProbe": {"httpGet": {"path": "/", "port": 80}},
  "resources": {
    "limits": {"cpu": "100m", "memory": "128Mi"},
    "requests": {"cpu": "50m", "memory": "64Mi"},
  },
}

sc_container_safe := object.union(sc_overhead, {
  "name": "ok",
  "securityContext": {"allowPrivilegeEscalation": false},
})

sc_container_unsafe := object.union(sc_overhead, {"name": "bad"})  # no securityContext

sc_container_explicit_true := object.union(sc_overhead, {
  "name": "worse",
  "securityContext": {"allowPrivilegeEscalation": true},
})

sc_deployment_safe := {
  "kind": "Deployment",
  "metadata": {"name": "d-ok"},
  "spec": {"template": {"spec": {"containers": [sc_container_safe]}}},
}

sc_deployment_unsafe := {
  "kind": "Deployment",
  "metadata": {"name": "d-bad"},
  "spec": {"template": {"spec": {"containers": [sc_container_unsafe]}}},
}

sc_deployment_explicit_true := {
  "kind": "Deployment",
  "metadata": {"name": "d-worse"},
  "spec": {"template": {"spec": {"containers": [sc_container_explicit_true]}}},
}

sc_deployment_unsafe_initcontainer := {
  "kind": "Deployment",
  "metadata": {"name": "d-init"},
  "spec": {"template": {"spec": {
    "containers": [sc_container_safe],
    "initContainers": [sc_container_unsafe],
  }}},
}

sc_daemonset_unsafe := {
  "kind": "DaemonSet",
  "metadata": {"name": "ds-bad"},
  "spec": {"template": {"spec": {"containers": [sc_container_unsafe]}}},
}

sc_cronjob_unsafe := {
  "kind": "CronJob",
  "metadata": {"name": "cj-bad"},
  "spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [sc_container_unsafe]}}}}},
}

# ── happy path ──────────────────────────────────────────────────────────────

test_safe_deployment_no_priv_escalation_deny {
  not has_message(deny, "allowPrivilegeEscalation") with input as sc_deployment_safe
}

# ── deny for missing securityContext / explicit true ────────────────────────

test_missing_security_context_denied {
  has_message(deny, "allowPrivilegeEscalation: false") with input as sc_deployment_unsafe
}

test_explicit_allow_priv_escalation_denied {
  has_message(deny, "allowPrivilegeEscalation: false") with input as sc_deployment_explicit_true
}

# ── initContainers also covered ─────────────────────────────────────────────

test_init_container_unsafe_denied {
  has_message(deny, "initContainer") with input as sc_deployment_unsafe_initcontainer
}

# ── kinds beyond Deployment ─────────────────────────────────────────────────

test_unsafe_daemonset_denied {
  has_message(deny, "DaemonSet 'ds-bad'") with input as sc_daemonset_unsafe
}

test_unsafe_cronjob_denied {
  has_message(deny, "CronJob 'cj-bad'") with input as sc_cronjob_unsafe
}
