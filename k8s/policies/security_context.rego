package main

# Every container must explicitly set allowPrivilegeEscalation: false.
# Without this, a process can gain more privileges than its parent — a common
# container escape vector.

privilege_escalation_disabled(container) {
  container.securityContext.allowPrivilegeEscalation == false
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not privilege_escalation_disabled(container)
  msg := sprintf(
    "Deployment '%s': container '%s' must set securityContext.allowPrivilegeEscalation: false",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.initContainers[_]
  not privilege_escalation_disabled(container)
  msg := sprintf(
    "Deployment '%s': initContainer '%s' must set securityContext.allowPrivilegeEscalation: false",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not privilege_escalation_disabled(container)
  msg := sprintf(
    "DaemonSet '%s': container '%s' must set securityContext.allowPrivilegeEscalation: false",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.initContainers[_]
  not privilege_escalation_disabled(container)
  msg := sprintf(
    "DaemonSet '%s': initContainer '%s' must set securityContext.allowPrivilegeEscalation: false",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Job"
  container := input.spec.template.spec.containers[_]
  not privilege_escalation_disabled(container)
  msg := sprintf(
    "Job '%s': container '%s' must set securityContext.allowPrivilegeEscalation: false",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "CronJob"
  container := input.spec.jobTemplate.spec.template.spec.containers[_]
  not privilege_escalation_disabled(container)
  msg := sprintf(
    "CronJob '%s': container '%s' must set securityContext.allowPrivilegeEscalation: false",
    [input.metadata.name, container.name],
  )
}
