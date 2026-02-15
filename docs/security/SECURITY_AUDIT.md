# Security Audit Summary

## Overview
This document summarizes the security vulnerabilities identified during the audit of the `homelab` repository and the remediations applied.

**Tools Used:**
- `checkov` (Infrastructure as Code Scanner)
- `tfsec` (Terraform Static Analysis)

## Findings & Remediations

### Infrastructure (Terraform - OCI)

**Vulnerabilities Identified:**
1.  **Legacy MetaData Service Enabled (`CKV_OCI_5`)**: Compute instances were configured with legacy metadata endpoints, which can be a security risk (SSRF).
2.  **Unencrypted Boot Volumes in Transit (`CKV_OCI_4`)**: Boot volumes were not configured to use in-transit encryption.

**Remediation:**
- Updated `infra/oci/modules/compute/main.tf` to explicitly disable legacy metadata endpoints (`are_legacy_imds_endpoints_disabled = true`).
- Enabled in-transit encryption for paravirtualized boot volumes (`is_pv_encryption_in_transit_enabled = true`).

### Kubernetes Manifests

**Common Vulnerabilities Identified:**
- **Missing Resource Limits/Requests**: Many deployments lacked CPU/Memory limits, leading to potential resource exhaustion (DoS).
- **Missing Security Context**: Containers were running without `securityContext`, often allowing root access or privilege escalation.
- **Using `latest` Image Tags**: Deployments were using mutable `latest` tags, which makes builds non-reproducible and can introduce unexpected changes.
- **Missing Probes**: Liveness and Readiness probes were missing, affecting availability and self-healing.

**Remediation:**

| Resource | File | Fixes Applied |
| :--- | :--- | :--- |
| **Prometheus** | `k8s/01-monitoring-core.yaml` | Pinned image version, added `securityContext` (runAsNonRoot, readOnlyRootFilesystem, drop capabilities), added resource limits. |
| **Grafana** | `k8s/01-monitoring-core.yaml` | Pinned image version, added `securityContext`, added resource limits. |
| **Loki** | `k8s/04-loki-server.yaml` | Added `securityContext` (runAsUser 10001, readOnlyRootFilesystem), added `emptyDir` for `/tmp`, added resource limits, added Probes. |
| **Kube State Metrics** | `k8s/03-kube-state-metrics.yaml` | Added `securityContext`, added resource limits, added Probes. |
| **Blackbox Exporter** | `k8s/06-blackbox.yaml` | Pinned image version, added `securityContext`, added resource limits, added Probes. |
| **Node Exporter** | `k8s/05-node-exporter.yaml` | Added `securityContext` (limited due to host access needs), added resource limits, added Probes. |
| **AdGuard Home** | `k8s/adguard.yaml` | Pinned image version, added resource limits, added Probes. Kept `privileged: true` as required for Host Network DNS. |
| **OTel Agent** | `k8s/02-otel-agent.yaml` | Added Liveness Probe (Health Check extension), added resource limits. Kept `privileged: true` as required for host metric collection. |

## Conclusion
The security posture of the infrastructure and Kubernetes deployments has been significantly improved. Critical infrastructure now uses encrypted transit and secure metadata. Kubernetes workloads are now resource-constrained, run with reduced privileges where possible, and have health checks configured.
