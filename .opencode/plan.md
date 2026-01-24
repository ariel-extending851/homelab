# Implementation Plan: Homelab Hybrid Cluster (Oracle Cloud + Raspberry Pi via Tailscale)

This plan outlines the phases and tasks required to provision the cloud infrastructure, set up GitOps, and manage the hybrid workload distribution.

## Phase 1: OCI Infrastructure Provisioning with Terraform

- [x] Task: Initialize Terraform project structure for OCI.
- [x] Task: Define OCI provider, authentication variables, and remote backend configuration.
- [x] Task: Create a reusable Terraform module for the OCI Virtual Cloud Network (VCN), subnets, and security groups.
- [x] Task: Create Terraform code to provision the required number of Always Free ARM Compute Instances. cccc1aa
- [~] Task: Implement a dynamic inventory script or use a Terraform provisioner to generate an Ansible inventory from the Terraform state.
- [x] Task: Align Terraform with Tailscale Infrastructure as Code best practices - Refactor cloud-init to use template files, ensure SSH hardening
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

- [x] Task: Create a new, dedicated Git repository for Kubernetes manifests (e.g., `hl-k8s-manifests`).
  - **Solution:** Using monorepo approach with `k8s/` directory in main homelab repo
- [x] Task: Write a Kubernetes manifest or Helm values file to install ArgoCD into the cluster.
  - **Documented:** Installation instructions in `k8s/gitops/README.md`
- [x] Task: Apply the ArgoCD manifest to the cluster using `kubectl`.
  - **Status:** Deployed and operational (App: `homelab-apps-root`, Health: Healthy)
- [x] Task: Create production applications (Monitoring Stack, SearXNG, GoLink, AdGuard)
  - **Deployed:** All apps in `k8s/apps/` with proper modular namespace architecture
- [x] Task: Create an ArgoCD `Application` custom resource manifest (App of Apps pattern)
  - **Created:** `k8s/gitops/apps-root.yaml` - Manages all apps in `k8s/apps/` recursively
- [x] Task: Apply the ArgoCD `Application` manifest to the cluster to trigger the first sync.
  - **Status:** ✅ Synced and Healthy (2026-01-23)
  - **Resolution:** Fixed kustomization pattern (replaced directory.recurse with root kustomization.yaml)
  - **Resolution:** Migrated to SSH authentication (Phase 6) - OCI egress throttling eliminated
  - **Current State:** All 10 applications syncing via GitOps (develop branch)
- [~] Task: Conductor - User Manual Verification 'Phase 3: GitOps Implementation with ArgoCD' (Protocol in workflow.md)
  - **Pending:** ArgoCD network issue resolution and branch configuration

## Phase 4: Applications & Workload Management

- [x] Task: Deploy GoLink (internal URL shortener) - Production-grade manifests with Tailscale integration
- [x] Task: **Migrate SearXNG to k3s-node-1** - Moved from RPi3 to Oracle Cloud for 12GB RAM capacity.
- [x] Task: **Optimize SearXNG** - Disabled image proxy to fix Tailscale relay latency.
- [x] Task: **Migrate to Tailscale Kubernetes Operator** - **COMPLETED (2026-01-23)**
  - **Commits:** 4 atomic, GPG-signed commits (76749b0, f5b9e4c, 975636b, 3dae3f1) pushed to `origin/develop`
  - **Architecture Change:** Replaced 6 sidecar containers with native Tailscale Operator + Ingress pattern
  - **Resource Savings:** 238m CPU (95% reduction), 178Mi memory (56% reduction), 400Mi storage freed
  - **Apps Migrated:** AdGuard Home, Grafana, Loki, Prometheus, SearXNG, GoLink
  - **Verification Status:** ✅ 5/6 apps operational via MagicDNS (`.tail57bf10.ts.net`)
  - **Prometheus Monitoring:** ✅ All 16 targets scraping successfully across modular namespaces
  - **ProxyClass:** ✅ All 6 proxy pods scheduled on k3s-node-0 (Oracle Cloud) as configured
- [x] Task: **FIXED AdGuard Home** - Resolved CrashLoopBackOff (2026-01-23)
  - **Root Cause:** Config schema version mismatch (v32 not supported by v0.107.43)
  - **Solution:** Upgraded image from v0.107.43 → v0.107.71 (latest stable)
  - **Status:** ✅ Running (1/1 Ready, DNS proxy operational on port 53)
  - **Location:** rasp-pi-03
- [ ] Task: **Migrate AdGuard Home** - Move from rasp-pi-03 to rasp-pi-04 (blocked by crash issue above)
- [x] Task: Deploy *** to rasp-pi-04 (Media Server) - **COMPLETED (2026-01-24)**
  - **PR:** #32 (merged to develop)
  - **Status:** ✅ OPERATIONAL
    - Pod: ***-69847ddbf-2zrjz (1/1 Ready, rasp-pi-04)
    - Tailscale Ingress: ***.tail57bf10.ts.net (ts-***-ingress-w6cc4-0)
    - Storage: 10Gi config PVC (***-config-pvc) + 5Gi cache
    - Resources: 500m-2000m CPU, 1Gi-3Gi memory
  - **Manifests:** k8s/apps/***/ (namespace, deployment, service, ingress, PVC)
  - **GitOps:** Integrated with ArgoCD App-of-Apps pattern
  - **Verification:** Health endpoint operational, Tailscale proxy routing active
  - **AWS Exam Parallel:** ECS Fargate placement (nodeSelector), EBS provisioning (PVC), ALB health checks (probes)
- [x] Task: Optimize SearXNG engine timeouts and image proxy settings to reduce latency < 1.0s

## Infrastructure Status

- **k3s-node-0** (Oracle Cloud, 4 cores, 24GB RAM): Control Plane + Tailscale Proxy Hub (Stable)
  - CPU: 90m (2%), Memory: 2302Mi (10%)
  - Hosts: 6 Tailscale Operator proxy pods (adguard, grafana, loki, prometheus, searxng, golink)
- **k3s-node-1** (Oracle Cloud, 4 cores, 24GB RAM): Heavy Workload Node (Stable)
  - CPU: 28m (1%), Memory: 1212Mi (5%)
  - Hosts: SearXNG (optimized for 12GB RAM capacity)
- **rasp-pi-03** (RPi3, 4 cores, 4GB RAM): Monitoring Canary + AdGuard Home (Stable)
  - CPU: 269m (7%), Memory: 474Mi (12%)
  - Status: ✅ AdGuard Home v0.107.71 operational (DNS proxy running)
- **rasp-pi-04** (RPi4, 4 cores, 8GB RAM): General Purpose ARM64 (Stable)
  - CPU: 298m (7%), Memory: 1153Mi (14%)
  - Hosts: Tailscale Operator controller
  - Target: AdGuard Home migration, *** deployment

## Phase 5: Governance & Security Guardrails

- [x] Task: Initialize GitHub Terraform provider in `infra/oci/github.tf`
- [x] Task: Define branch protection rules for `main` branch (required checks, 1 approval, signed commits, enforce admins)
- [x] Task: Define branch protection rules for `develop` branch (same strict policies as main)
- [x] Task: Configure repository hardening (squash merge only, delete branch on merge)
- [x] Task: **FIX:** Consolidate duplicate `terraform {}` blocks - moved GitHub provider to `main.tf` (DRY principle)
- [x] Task: Execute `terraform init` to install GitHub provider
- [x] Task: Execute `terraform plan` to preview GitHub configuration changes
- [x] Task: Execute `terraform apply` to enforce branch protection rules
- [x] Task: **PR Review Adjustments (PR #20):**
  - **Security:** Remove `hosts.ini` from VCS (exposes dynamic IPs) - added to `.gitignore`
  - **Refactoring:** Apply DRY principle to branch protection using `for_each` loop
  - **Documentation:** Fix GitHub Security Log URL (personal repo vs organization)
  - **Documentation:** Correct misleading comments on `allows_deletions = false`
  - **Documentation:** Fix GitHub token scope description (`repo` + `admin:repo_hook`)
  - **Security (Round 2):** Enable `require_last_push_approval = true` to prevent unreviewed code
  - **Documentation (Round 2):** Update `terraform import` commands for `for_each` syntax
- [x] Task: Verify branch protection via GitHub UI or `gh api` command
- [x] Task: Document GitHub PAT generation process in `docs/operations.md`
- [x] Task: Conductor - User Manual Verification 'Phase 5: Governance & Security Guardrails'
- [x] Task: **Review Threads Resolved:** 8/8 threads resolved via GraphQL API
- [x] Task: **CI Upgrade:** Implement polyglot validation (Terraform + TFLint, YAML Lint, ShellCheck)
- [x] Task: **Linting Remediation:** Fixed 32 errors (Terraform, YAML indentation, ShellCheck warnings)
- [x] Task: **Pipeline Gate:** Implemented aggregation pattern for status checks
- [x] Task: **State Migration:** Executed `terraform state mv` for `for_each` refactoring
- [x] Task: **PR #20 Merged:** Successfully merged to `develop` branch with squash commit
- [x] Task: Conductor - User Manual Verification 'Phase 5: Governance & Security Guardrails'

## Phase 6: Advanced GitOps & App Lifecycle

- [x] Task: Generate ED25519 SSH keypair for ArgoCD authentication
- [x] Task: Create SSH directory structure and security guardrails (.gitignore exclusions)
- [x] Task: Develop `create-argocd-ssh-secret.sh` script for Kubernetes secret generation
- [x] Task: Update `apps-root.yaml` to use SSH URL (`git@github.com:ariel99gf/homelab.git`)
- [x] Task: Change ArgoCD target branch from `HEAD` to `develop` for alignment with governance
- [x] Task: Create `apply-phase6-gitops.sh` orchestration script for automated deployment
- [x] Task: **USER ACTION:** Add SSH public key to GitHub Deploy Keys (read-only)
- [x] Task: Execute `k8s/gitops/apply-phase6-gitops.sh` to apply Phase 6 changes
- [x] Task: Verify ArgoCD repository connection via SSH (no more OCI throttling)
- [x] Task: Monitor all applications reach 'Healthy' and 'Synced' state
- [x] Task: (Optional) Migrate ArgoCD base installation from YAML to Helm Chart
- [x] Task: Conductor - User Manual Verification 'Phase 6: Advanced GitOps & App Lifecycle'

## Recent Migrations (2026-01-23)

- **Tailscale Architecture:** Sidecar → Operator pattern (238m CPU, 178Mi memory, 400Mi storage freed)
- **GitOps Status:** ArgoCD operational, local sync completed, GitHub fetch pending (OCI egress throttling)
- **Phase 6 Initiated:** SSH authentication configured to resolve OCI egress throttling (awaiting user deployment)
