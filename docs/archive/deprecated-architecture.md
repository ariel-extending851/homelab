---
DEPRECATED: This document refers to an old architecture based on Oracle Cloud Infrastructure (OCI) and is kept for historical purposes only. The current architecture runs on AWS.
---

# Technology Stack

This document outlines the core technologies and tools utilized in the homelab project. This stack has been selected to support a robust, automated, and portable hybrid Kubernetes environment, while providing comprehensive hands-on experience in modern DevOps practices.

## Infrastructure as Code (IaC)

- **Terraform:** Used for provisioning and managing infrastructure resources across both cloud environments (Oracle Cloud) and local development environments (using a local hypervisor provider like libvirt/QEMU).
- **Packer:** Utilized for creating custom, pre-configured machine images (e.g., Raspberry Pi OS images), ensuring immutable infrastructure and consistent deployments.
- **Ansible:** Employed for configuration management, automating the setup of operating systems, installing k3s clusters, and other software provisioning tasks on both physical and virtual machines.

## Containerization & Orchestration

- **Docker Buildx:** Essential for building multi-architecture container images (amd64 and arm64), ensuring applications can run seamlessly across diverse hardware (PC, Oracle Cloud Always Free tier, Raspberry Pi ARM).
- **Kubernetes (k3s):** The chosen lightweight Kubernetes distribution for both the on-premise Raspberry Pi cluster and the self-hosted cluster on Oracle Cloud's VM.Standard3.Flex instances (2 OCPUs, 12GB RAM) within the Always Free tier Compute Instances. This provides a consistent orchestration layer across the hybrid environment.
- **ArgoCD:** Implemented as the GitOps tool to manage continuous deployment and synchronization of Kubernetes applications and configurations from a Git repository to all connected clusters.

## Cloud Platforms

- **Oracle Cloud Infrastructure (OCI):** Specifically leveraging the VM.Standard3.Flex instances (2 OCPUs, 12GB RAM) within the Always Free tier Compute Instances for hosting the primary cloud-based k3s Kubernetes cluster, providing a cost-effective and performant cloud environment.

## Virtualization & Emulation (Local Development)

- **Local Hypervisor Provider (e.g., libvirt/QEMU):** Used in conjunction with Terraform for provisioning local virtual machines, enabling consistent development and testing environments that can emulate different architectures (e.g., ARM VMs on an x86 PC).

## Monitoring & Observability

- **Prometheus:** A leading open-source monitoring system, used for collecting and storing metrics from Kubernetes clusters and deployed applications.
- **Grafana:** The open-source platform for analytics and interactive visualization, used to create dashboards from Prometheus data.

## Application (Example)

- **Samsung Health Dashboard Application:** A custom application to demonstrate the end-to-end deployment pipeline, connecting to Samsung Health data and exposing metrics for Prometheus/Grafana.
