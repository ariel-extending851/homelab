# Specification: Setup Oracle Cloud k3s Cluster with Terraform and ArgoCD for GitOps

## 1. Overview
This track covers the foundational setup of the cloud-based Kubernetes environment. The objective is to use Infrastructure as Code (Terraform) to provision the necessary infrastructure on Oracle Cloud's Always Free ARM instances. A k3s Kubernetes cluster will then be installed and configured on these instances using Ansible. Finally, ArgoCD will be installed and configured to establish a GitOps workflow, preparing the cluster for automated application deployments.

## 2. Functional Requirements
- The Terraform configuration MUST provision OCI resources, including ARM Compute Instances, a Virtual Cloud Network (VCN) with necessary subnets, and appropriate Security Lists/Firewall rules.
- An Ansible playbook MUST be used to install and configure a multi-node k3s cluster on the provisioned OCI instances.
- The resulting k3s cluster MUST be accessible via `kubectl` from the local development workstation.
- ArgoCD MUST be installed into the cluster.
- ArgoCD MUST be configured to synchronize with a designated Git repository.

## 3. Non-Functional Requirements
- All infrastructure and configuration code (Terraform, Ansible) SHOULD be modular, reusable, and well-documented.
- The entire process, from infrastructure provisioning to cluster setup, MUST be automated, requiring minimal manual intervention.

## 4. Acceptance Criteria
- A `terraform apply` command successfully creates all specified OCI resources without errors.
- `kubectl get nodes -o wide` shows all provisioned OCI instances as `Ready` nodes in the cluster.
- The ArgoCD UI is accessible through port-forwarding or an Ingress.
- A simple "hello-world" application, defined in the designated Git repository, is successfully deployed and synchronized in the cluster by ArgoCD after an initial `git push`.

## 5. Out of Scope
- Provisioning the on-premise Raspberry Pi cluster.
- Deploying the full Samsung Health application stack.
- Advanced ArgoCD configurations (e.g., App of Apps pattern, multi-cluster management).
