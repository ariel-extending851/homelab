# Initial Concept
The project aims to create a hybrid, multi-cluster Kubernetes environment. One cluster will be provisioned using a **k3s cluster on Oracle Cloud's Always Free ARM Compute Instances** via Terraform. This cloud cluster will serve as a central point for GitOps management and consolidated monitoring for all environments. A second, on-premise cluster will be built on Raspberry Pi hardware using Packer for image creation and Ansible for k3s installation.

Both clusters will be managed from a central workstation, with application deployments unified through a GitOps workflow using ArgoCD. This will allow for deploying applications like a Samsung Health dashboard with Prometheus/Grafana monitoring to both cloud and on-premise environments via a single `git push`.

## Project Vision & Goals
The primary vision is to build a production-grade, hybrid cloud platform for self-hosting applications, emphasizing automation, portability, and modern DevOps practices. The **k3s cluster on Oracle Cloud's Always Free ARM Compute Instances** will act as the primary operational hub, centralizing GitOps deployments and monitoring across all environments. The project serves as a practical, hands-on learning experience to develop and showcase skills relevant to a senior DevOps engineering role.

## Target Audience
The primary user of this homelab environment is the developer themself. The platform is a personal sandbox for learning, experimentation, and building projects for a professional portfolio.

## Success Criteria
The project will be considered successful when it serves as a tangible demonstration of proficiency with a modern DevOps toolchain. The key outcome is gaining and proving hands-on experience with the following technologies to build a strong portfolio for a DevOps role:
-   **Infrastructure as Code:** Terraform, Packer, Ansible
-   **Container Orchestration:** Kubernetes (k3s on both cloud and on-premise ARM VMs)
-   **GitOps:** ArgoCD
-   **Multi-Architecture Builds:** Docker Buildx for amd64 and arm64
-   **Hybrid Cloud Management:** Managing distinct cloud and on-premise clusters.
