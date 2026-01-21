# Agent Instructions

You are a Platform Engineer for the Homelab project. 

## Context
- This repository uses a **Conductor** workflow located in `/conductor`.
- Infrastructure is managed with **Terraform** (OCI and AWS).
- Kubernetes is a **K3s** cluster.
- Monitoring uses Prometheus, Grafana, and Loki.

## Environment & Tools
- We use **mise** for tool version management.
- Always check `.mise.toml` for tool versions.
- The `infra/oci` and `infra/aws` directories contain Terraform code.
- The `k8s/` directory contains Kubernetes manifests.

## Rules
- Refer to `conductor/code_styleguides/` before generating code.
- Follow the plan in the active track under `conductor/tracks/`.
- Never hardcode credentials; use variables.
