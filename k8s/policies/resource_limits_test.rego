package main

# Test fixtures for resource_limits.rego. Helpers in test_helpers.rego.

rl_overhead := {
  "readinessProbe": {"httpGet": {"path": "/", "port": 80}},
  "livenessProbe": {"httpGet": {"path": "/", "port": 80}},
  "securityContext": {"allowPrivilegeEscalation": false},
}

rl_container_with_limits := object.union(rl_overhead, {
  "name": "ok",
  "resources": {
    "limits": {"cpu": "100m", "memory": "128Mi"},
    "requests": {"cpu": "50m", "memory": "64Mi"},
  },
})

rl_container_no_limits := object.union(rl_overhead, {"name": "bad"})

rl_deployment_ok := {
  "kind": "Deployment",
  "metadata": {"name": "d-ok"},
  "spec": {"template": {"spec": {"containers": [rl_container_with_limits]}}},
}

rl_deployment_bad := {
  "kind": "Deployment",
  "metadata": {"name": "d-bad"},
  "spec": {"template": {"spec": {"containers": [rl_container_no_limits]}}},
}

rl_daemonset_bad := {
  "kind": "DaemonSet",
  "metadata": {"name": "ds-bad"},
  "spec": {"template": {"spec": {"containers": [rl_container_no_limits]}}},
}

rl_job_bad := {
  "kind": "Job",
  "metadata": {"name": "j-bad"},
  "spec": {"template": {"spec": {"containers": [rl_container_no_limits]}}},
}

rl_cronjob_bad := {
  "kind": "CronJob",
  "metadata": {"name": "cj-bad"},
  "spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [rl_container_no_limits]}}}}},
}

# ── happy path ──────────────────────────────────────────────────────────────

test_deployment_with_limits_no_resource_denies {
  not has_message(deny, "CPU limit") with input as rl_deployment_ok
  not has_message(deny, "memory limit") with input as rl_deployment_ok
  not has_message(deny, "CPU request") with input as rl_deployment_ok
  not has_message(deny, "memory request") with input as rl_deployment_ok
}

# ── unhappy path: each missing field surfaces a specific message ────────────

test_deployment_missing_resources_denies_cpu_limit {
  has_message(deny, "CPU limit") with input as rl_deployment_bad
}

test_deployment_missing_resources_denies_memory_limit {
  has_message(deny, "memory limit") with input as rl_deployment_bad
}

test_deployment_missing_resources_denies_cpu_request {
  has_message(deny, "CPU request") with input as rl_deployment_bad
}

test_deployment_missing_resources_denies_memory_request {
  has_message(deny, "memory request") with input as rl_deployment_bad
}

# ── coverage of other workload kinds ────────────────────────────────────────

test_daemonset_missing_resources_denied {
  has_message(deny, "DaemonSet 'ds-bad'") with input as rl_daemonset_bad
}

test_job_missing_resources_denied {
  has_message(deny, "Job 'j-bad'") with input as rl_job_bad
}

test_cronjob_missing_resources_denied {
  has_message(deny, "CronJob 'cj-bad'") with input as rl_cronjob_bad
}
