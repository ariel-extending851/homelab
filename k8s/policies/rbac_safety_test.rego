package main

# Test fixtures for rbac_safety.rego.

clusterrole_wildcard_verb := {
  "kind": "ClusterRole",
  "metadata": {"name": "rogue-cr"},
  "rules": [{"verbs": ["*"], "resources": ["pods"], "apiGroups": [""]}],
}

clusterrole_wildcard_resource := {
  "kind": "ClusterRole",
  "metadata": {"name": "rogue-cr-2"},
  "rules": [{"verbs": ["get"], "resources": ["*"], "apiGroups": [""]}],
}

clusterrole_velero_wildcard := {
  "kind": "ClusterRole",
  "metadata": {"name": "velero"},
  "rules": [{"verbs": ["*"], "resources": ["*"], "apiGroups": ["*"]}],
}

clusterrole_safe := {
  "kind": "ClusterRole",
  "metadata": {"name": "safe-cr"},
  "rules": [{"verbs": ["get", "list"], "resources": ["pods"], "apiGroups": [""]}],
}

role_with_pods_exec := {
  "kind": "Role",
  "metadata": {"name": "shell-role"},
  "rules": [{"verbs": ["create"], "resources": ["pods/exec"], "apiGroups": [""]}],
}

# ── wildcards in unallowed clusterroles → deny ──────────────────────────────

test_unallowed_wildcard_verb_denied {
  count(deny) > 0 with input as clusterrole_wildcard_verb
}

test_unallowed_wildcard_resource_denied {
  count(deny) > 0 with input as clusterrole_wildcard_resource
}

# ── allowlisted clusterroles (velero) → no deny ─────────────────────────────

test_velero_wildcard_allowed {
  count(deny) == 0 with input as clusterrole_velero_wildcard
}

# ── safe clusterrole (no wildcards) → no deny ───────────────────────────────

test_safe_clusterrole_passes {
  count(deny) == 0 with input as clusterrole_safe
}

# ── Role with pods/exec → warn ──────────────────────────────────────────────

test_pods_exec_warns {
  count(warn) == 1 with input as role_with_pods_exec
}
