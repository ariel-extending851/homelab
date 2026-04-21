package main

# Every container in a Deployment must declare CPU and memory limits.
# Containers without limits are unbounded and can starve other workloads.

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.cpu
  msg := sprintf(
    "Deployment '%s': container '%s' is missing a CPU limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.memory
  msg := sprintf(
    "Deployment '%s': container '%s' is missing a memory limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests.cpu
  msg := sprintf(
    "Deployment '%s': container '%s' is missing a CPU request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Deployment"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests.memory
  msg := sprintf(
    "Deployment '%s': container '%s' is missing a memory request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.cpu
  msg := sprintf(
    "DaemonSet '%s': container '%s' is missing a CPU limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.memory
  msg := sprintf(
    "DaemonSet '%s': container '%s' is missing a memory limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests.cpu
  msg := sprintf(
    "DaemonSet '%s': container '%s' is missing a CPU request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "DaemonSet"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests.memory
  msg := sprintf(
    "DaemonSet '%s': container '%s' is missing a memory request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Job"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.cpu
  msg := sprintf(
    "Job '%s': container '%s' is missing a CPU limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Job"
  container := input.spec.template.spec.containers[_]
  not container.resources.limits.memory
  msg := sprintf(
    "Job '%s': container '%s' is missing a memory limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Job"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests.cpu
  msg := sprintf(
    "Job '%s': container '%s' is missing a CPU request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "Job"
  container := input.spec.template.spec.containers[_]
  not container.resources.requests.memory
  msg := sprintf(
    "Job '%s': container '%s' is missing a memory request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "CronJob"
  container := input.spec.jobTemplate.spec.template.spec.containers[_]
  not container.resources.limits.cpu
  msg := sprintf(
    "CronJob '%s': container '%s' is missing a CPU limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "CronJob"
  container := input.spec.jobTemplate.spec.template.spec.containers[_]
  not container.resources.limits.memory
  msg := sprintf(
    "CronJob '%s': container '%s' is missing a memory limit",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "CronJob"
  container := input.spec.jobTemplate.spec.template.spec.containers[_]
  not container.resources.requests.cpu
  msg := sprintf(
    "CronJob '%s': container '%s' is missing a CPU request",
    [input.metadata.name, container.name],
  )
}

deny[msg] {
  input.kind == "CronJob"
  container := input.spec.jobTemplate.spec.template.spec.containers[_]
  not container.resources.requests.memory
  msg := sprintf(
    "CronJob '%s': container '%s' is missing a memory request",
    [input.metadata.name, container.name],
  )
}
