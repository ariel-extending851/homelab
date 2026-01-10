# Implementation Plan: Setup Oracle Cloud k3s Cluster with Terraform and ArgoCD for GitOps

This plan outlines the phases and tasks required to provision the cloud infrastructure and set up the GitOps workflow.

## Phase 1: OCI Infrastructure Provisioning with Terraform
- [x] Task: Initialize Terraform project structure for OCI.
- [x] Task: Define OCI provider, authentication variables, and remote backend configuration.
- [x] Task: Create a reusable Terraform module for the OCI Virtual Cloud Network (VCN), subnets, and security groups.
- [x] Task: Create Terraform code to provision the required number of Always Free ARM Compute Instances. cccc1aa
- [ ] Task: Implement a dynamic inventory script or use a Terraform provisioner to generate an Ansible inventory from the Terraform state.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: OCI Infrastructure Provisioning with Terraform' (Protocol in workflow.md)

## Phase 2: k3s Cluster Installation with Ansible
- [ ] Task: Create a new Ansible role for k3s installation and configuration.
- [ ] Task: Write a playbook that uses the dynamic inventory to target the OCI instances.
- [ ] Task: Write Ansible tasks to install k3s on the first node, designating it as the server.
- [ ] Task: Write Ansible tasks to retrieve the join token from the server node.
- [ ] Task: Write Ansible tasks to install k3s on the remaining nodes as agents, using the retrieved token.
- [ ] Task: Write an Ansible task to fetch the `kubeconfig` file from the server node to the local workstation.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: k3s Cluster Installation with Ansible' (Protocol in workflow.md)

## Phase 3: GitOps Implementation with ArgoCD
- [ ] Task: Create a new, dedicated Git repository for Kubernetes manifests (e.g., `hl-k8s-manifests`).
- [ ] Task: Write a Kubernetes manifest or Helm values file to install ArgoCD into the cluster.
- [ ] Task: Apply the ArgoCD manifest to the cluster using `kubectl`.
- [ ] Task: Create a "hello-world" application manifest (e.g., Deployment and Service) and push it to the new Git repository.
- [ ] Task: Create an ArgoCD `Application` custom resource manifest that points to the "hello-world" app in the Git repository.
- [ ] Task: Apply the ArgoCD `Application` manifest to the cluster to trigger the first sync.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: GitOps Implementation with ArgoCD' (Protocol in workflow.md)
