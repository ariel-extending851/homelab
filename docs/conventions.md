# Product Guidelines

This document outlines the standard naming, versioning, and style conventions to be used across all components of the homelab project. Adherence to these guidelines ensures consistency, clarity, and professionalism.

## 1. Naming Conventions

All resources created for or by this project MUST be prefixed with `hl-`. This means all-lowercase letters with words separated by hyphens.

### 1.1 Prefix Rule

All project-related resources MUST be prefixed with `hl-`. This prefix, short for "homelab," provides immediate context and allows for easy grouping and filtering of resources, especially in cloud environments.

### 1.2 Case Style Rule

All resource names MUST use `kebab-case`. This means all-lowercase letters with words separated by hyphens.

### 1.3 Examples

The following examples demonstrate the combined naming convention for various resource types:

-   **Git Repositories:**
    -   `hl-k8s-manifests`
    -   `hl-infra-provisioning`

-   **Cloud Resources (VMs, VPCs, etc.):**
    -   `hl-k3s-control-plane-01`
    -   `hl-main-vpc`
    -   `hl-public-subnet`

-   **Kubernetes Resources (Namespaces, Services, etc.):**
    -   `hl-argocd`
    -   `hl-monitoring`
    -   `samsung-health-app` (Note: The `hl-` prefix may be omitted for application-specific resources within a dedicated, project-scoped namespace.)

## 2. Versioning Conventions

All versioned artifacts, including application code, container images, and infrastructure modules, MUST adhere to the Semantic Versioning (SemVer) standard.

### 2.1 SemVer Standard

The versioning format is `MAJOR.MINOR.PATCH` (e.g., `v1.2.3`).

-   **MAJOR** version is incremented for incompatible API changes.
-   **MINOR** version is incremented for adding functionality in a backwards-compatible manner.
-   **PATCH** version is incremented for backwards-compatible bug fixes.

### 2.2 Application Examples

-   **Application Releases / Git Tags:**
    -   `v1.0.0`
    -   `v1.1.2`

-   **Container Image Tags:**
    -   `ghcr.io/your-user/hl-webapp:v1.0.0`

-   **Terraform Module Versions:**
    ```hcl
    module "vpc" {
      source = "./modules/vpc?ref=v1.2.0"
    }
    ```