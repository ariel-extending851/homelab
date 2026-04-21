package main

# Every Deployment must configure a readinessProbe on all containers.
# Without it, Kubernetes sends traffic before the app is ready, causing
# errors during rollouts and restarts.

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.readinessProbe
  msg := sprintf(
    "Deployment '%s': container '%s' is missing a readinessProbe",
    [input.metadata.name, container.name],
  )
}

# livenessProbe is a warning — valuable but not always safe to require
# (a wrong liveness probe restarts healthy containers).
warn[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.livenessProbe
  msg := sprintf(
    "Deployment '%s': container '%s' has no livenessProbe (recommended)",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not container.readinessProbe
  msg := sprintf(
    "DaemonSet '%s': container '%s' is missing a readinessProbe",
    [input.metadata.name, container.name],
  )
}

warn[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not container.livenessProbe
  msg := sprintf(
    "DaemonSet '%s': container '%s' has no livenessProbe (recommended)",
    [input.metadata.name, container.name],
  )
}
