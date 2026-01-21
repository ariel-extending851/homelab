# Project Overview

This repository contains the infrastructure and configuration for a hybrid homelab environment. The goal is to create a production-grade, hybrid cloud platform for self-hosting applications, emphasizing automation, portability, and modern DevOps practices.

The environment consists of two main parts:

1.  **Oracle Cloud Infrastructure (OCI):** A k3s cluster is provisioned on Oracle Cloud's Always Free ARM Compute Instances using Terraform. This cloud cluster serves as the central point for GitOps management and consolidated monitoring.
2.  **On-premise:** A second k3s cluster is intended to be run on Raspberry Pi hardware.

The entire environment is managed using a GitOps workflow with ArgoCD, allowing for application deployments to both cloud and on-premise clusters via a single `git push`. Monitoring is handled by Prometheus and Grafana.

## Key Technologies

*   **Infrastructure as Code:** Terraform, Packer, Ansible
*   **Container Orchestration:** Kubernetes (k3s)
*   **GitOps:** ArgoCD
*   **Multi-Architecture Builds:** Docker Buildx
*   **Cloud Provider:** Oracle Cloud Infrastructure (OCI)
*   **Monitoring:** Prometheus, Grafana

# Building and Running

## Development Environment

This project uses a dev container to provide a consistent development environment. The dev container comes with all the necessary tools pre-installed.

To set up the development environment, open this repository in a dev container. The `postCreateCommand` will automatically run `mise install` to install the tools defined in `.mise.toml`.

## Infrastructure Provisioning

The cloud infrastructure on OCI is provisioned using Terraform.

**Prerequisites:**

*   OCI account
*   Terraform installed (`mise install` will handle this in the dev container)
*   OCI credentials configured

**To provision the infrastructure:**

1.  Navigate to the `infra/oci` directory.
2.  Initialize Terraform:
    ```bash
    terraform init
    ```
3.  Review the plan:
    ```bash
    terraform plan
    ```
4.  Apply the changes:
    ```bash
    terraform apply
    ```

## Kubernetes Configuration

The Kubernetes manifests are located in the `k8s` directory. These are intended to be deployed via a GitOps tool like ArgoCD. The manifests define the monitoring stack (Prometheus, Grafana), as well as other applications.

# Development Conventions

The project follows standard conventions for Terraform and Kubernetes development. The use of a dev container with specific tools and settings enforced by `.mise.toml` and `devcontainer.json` helps maintain a consistent development environment.
