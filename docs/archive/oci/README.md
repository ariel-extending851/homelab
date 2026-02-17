---
DEPRECATED: This document refers to an old architecture based on Oracle Cloud Infrastructure (OCI) and is kept for historical purposes only. The current architecture runs on AWS.
---

# Specifications & Code Map (The Pin)

> Use this file to discover where resources are defined before creating new ones.

## Infrastructure (Terraform & OCI)
- **Compute/VMs:** `infra/oci/modules/compute/` (ARM Instance definitions)
- **Network/VCN:** `infra/oci/modules/network/` (VCN, Subnets, Security Lists)
- **Variables:** `infra/oci/variables.tf` and `infra/oci/terraform.tfvars`
- **Output:** `infra/oci/outputs.tf`

## Kubernetes (Apps & GitOps)
- **Monitoring:** `k8s/apps/prometheus/`, `k8s/apps/grafana/`, `k8s/apps/loki/`
- **Networking:** `k8s/apps/adguard/`, `k8s/system/tailscale-operator/`
- **GitOps (ArgoCD):** `k8s/gitops/`
- **Base Apps:** `k8s/apps/`

## Governance & Scripts
- **CI/CD:** `.github/workflows/`
- **Utility Scripts:** `bin/`
- **Execution Plan:** `plan.md`
- **Project Memory:** `memory.md`
