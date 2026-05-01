package main

# Shared helpers for *_test.rego files. All policies + tests share
# `package main`, so duplicate rule definitions across files conflict —
# put any cross-file helper here exactly once.

# Returns true if any message in `set` contains `needle` as a substring.
# Use to assert per-rule denies/warns instead of brittle count(deny)
# (which aggregates across all four policy files).
has_message(set, needle) {
  some msg
  set[msg]
  contains(msg, needle)
}

# Container that satisfies probes + resources + securityContext, so a
# fixture using it produces 0 denies from any of the four policies.
fully_compliant_container := {
  "name": "c1",
  "readinessProbe": {"httpGet": {"path": "/", "port": 80}},
  "livenessProbe": {"httpGet": {"path": "/", "port": 80}},
  "resources": {
    "limits": {"cpu": "100m", "memory": "128Mi"},
    "requests": {"cpu": "50m", "memory": "64Mi"},
  },
  "securityContext": {"allowPrivilegeEscalation": false},
}
