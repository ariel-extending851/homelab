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
  - **Status:** Applied. ArgoCD is operational but experiencing GitHub fetch timeouts due to OCI egress throttling.
  - **Workaround:** Local sync via `kubectl apply -k k8s/apps/<app>/` executed successfully (2026-01-23)
  - **Action Required:** Update ArgoCD to track `develop` branch: `kubectl patch application homelab-apps-root -n argocd --type merge -p '{"spec":{"source":{"targetRevision":"develop"}}}'`
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
- [!] Task: **FIX AdGuard Home** - Currently in CrashLoopBackOff (154 restarts over 12h)
  - **Root Cause:** Config schema version mismatch (v32 not supported by v0.107.43)
  - **Location:** rasp-pi-03
  - **Action Required:** Upgrade AdGuard Home image or downgrade config schema
  - **Priority:** HIGH (DNS service unavailable)
- [ ] Task: **Migrate AdGuard Home** - Move from rasp-pi-03 to rasp-pi-04 (blocked by crash issue above)
- [ ] Task: Deploy *** to rasp-pi-04 (Media Server).
- [x] Task: Optimize SearXNG engine timeouts and image proxy settings to reduce latency < 1.0s

## Infrastructure Status
- **k3s-node-0** (Oracle Cloud, 4 cores, 24GB RAM): Control Plane + Tailscale Proxy Hub (Stable)
  - CPU: 90m (2%), Memory: 2302Mi (10%)
  - Hosts: 6 Tailscale Operator proxy pods (adguard, grafana, loki, prometheus, searxng, golink)
- **k3s-node-1** (Oracle Cloud, 4 cores, 24GB RAM): Heavy Workload Node (Stable)
  - CPU: 28m (1%), Memory: 1212Mi (5%)
  - Hosts: SearXNG (optimized for 12GB RAM capacity)
- **rasp-pi-03** (RPi3, 4 cores, 4GB RAM): Monitoring Canary + AdGuard Home (DEGRADED)
  - CPU: 269m (7%), Memory: 474Mi (12%)
  - Issue: AdGuard Home in CrashLoopBackOff (config schema v32 unsupported by v0.107.43)
- **rasp-pi-04** (RPi4, 4 cores, 8GB RAM): General Purpose ARM64 (Stable)
  - CPU: 298m (7%), Memory: 1153Mi (14%)
  - Hosts: Tailscale Operator controller
  - Target: AdGuard Home migration, *** deployment

## Recent Migrations (2026-01-23)
- **Tailscale Architecture:** Sidecar → Operator pattern (238m CPU, 178Mi memory, 400Mi storage freed)
- **GitOps Status:** ArgoCD operational, local sync completed, GitHub fetch pending (OCI egress throttling)
