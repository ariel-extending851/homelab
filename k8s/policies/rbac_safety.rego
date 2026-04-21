package main

# ClusterRoles must not use wildcard verbs or resources — these grant
# unrestricted access and violate least-privilege.

deny[msg] {
  input.kind == "ClusterRole"
  rule := input.rules[_]
  rule.verbs[_] == "*"
  msg := sprintf(
    "ClusterRole '%s': wildcard verb '*' is not allowed — enumerate specific verbs",
    [input.metadata.name],
  )
}

deny[msg] {
  input.kind == "ClusterRole"
  rule := input.rules[_]
  rule.resources[_] == "*"
  msg := sprintf(
    "ClusterRole '%s': wildcard resource '*' is not allowed — enumerate specific resources",
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
