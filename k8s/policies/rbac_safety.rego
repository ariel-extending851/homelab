package main

# ClusterRoles must not use wildcard verbs or resources by default — these grant
# unrestricted access and violate least-privilege.
#
# A documented allowlist exempts ClusterRoles whose function legitimately
# requires broad access (cluster backup, GitOps reconciliation, etc.).
# Adding to this set requires justification — see k8s/policies/README.md.

wildcard_allowed_clusterroles := {
  "velero",                            # cluster backup/DR — must reify any CRD
  "argocd-application-controller",     # GitOps reconciliation — must apply any CRD
  "argocd-server",                     # GitOps API/UI — read+write app state
}

deny[msg] {
  input.kind == "ClusterRole"
  not wildcard_allowed_clusterroles[input.metadata.name]
  rule := input.rules[_]
  rule.verbs[_] == "*"
  msg := sprintf(
    "ClusterRole '%s': wildcard verb '*' is not allowed — enumerate specific verbs (or add to wildcard_allowed_clusterroles in rbac_safety.rego with justification in k8s/policies/README.md)",
    [input.metadata.name],
  )
}

deny[msg] {
  input.kind == "ClusterRole"
  not wildcard_allowed_clusterroles[input.metadata.name]
  rule := input.rules[_]
  rule.resources[_] == "*"
  msg := sprintf(
    "ClusterRole '%s': wildcard resource '*' is not allowed — enumerate specific resources (or add to wildcard_allowed_clusterroles in rbac_safety.rego with justification in k8s/policies/README.md)",
    [input.metadata.name],
  )
}

# pods/exec grants interactive shell access to any pod — flag for review.
warn[msg] {
  input.kind == "Role"
  rule := input.rules[_]
  rule.resources[_] == "pods/exec"
  msg := sprintf(
    "Role '%s': pods/exec grants shell access to pods — ensure this is intentional",
    [input.metadata.name],
  )
}
