# GitOps Deployment Status

**Date:** 2026-01-23
**Status:** ⚠️ Partial - Network Limitation Identified

---

## ✅ Completed Tasks

### 1. Code Changes Committed to Git
- ✅ **Commit a133e94**: Fix monitoring stack - migrated to modular namespace architecture
- ✅ **Commit e7432c9**: Implemented ArgoCD app-of-apps pattern
- ✅ **Commit 1eaf88d**: Updated Phase 3 plan status
- ✅ **All commits pushed** to `origin/develop`

### 2. ArgoCD Installation
- ✅ ArgoCD installed successfully in `argocd` namespace
- ✅ All ArgoCD pods running and healthy:
  - argocd-application-controller
  - argocd-applicationset-controller
  - argocd-dex-server
  - argocd-notifications-controller
  - argocd-redis
  - argocd-repo-server
  - argocd-server

### 3. App-of-Apps Manifest Created
- ✅ `k8s/gitops/apps-root.yaml` created with proper configuration
- ✅ Recursive directory discovery enabled
- ✅ Auto-sync, prune, and self-heal policies configured
- ✅ Manifest applied to cluster successfully

### 4. Monitoring Stack Operational
- ✅ Prometheus: Running (1/1)
- ✅ Grafana: Running (1/1) - Datasources connected
- ✅ Loki: Running (1/1)
- ✅ Blackbox Exporter: Running (1/1)
- ✅ Kube State Metrics: Running (1/1)
- ✅ Node Exporter: Running (4/4 DaemonSet)
- ✅ OTEL Collector: Running (4/4 DaemonSet)

---

## ⚠️ Known Issue: Pod Outbound TCP Connectivity

### Problem Description
ArgoCD cannot clone the Git repository from GitHub due to network restrictions:

**Error:**
```
Failed to load target state: failed to generate manifest for source 1 of 1:
rpc error: code = Unknown desc = failed to list refs:
Get "https://github.com/ariel99gf/homelab.git/info/refs?service=git-upload-pack":
context deadline exceeded (Client.Timeout exceeded while awaiting headers)
```

### Root Cause Analysis

Diagnostic testing revealed:
- ✅ DNS resolution works (github.com resolves correctly)
- ✅ ICMP works (ping to 8.8.8.8 successful)
- ❌ Outbound TCP/HTTPS blocked (curl to GitHub times out)
- ✅ Host machine can reach GitHub (curl successful from host)

**Conclusion:** Pod network configuration prevents outbound TCP connections to external services.

### Potential Causes
1. **Oracle Cloud Security Groups**: Outbound TCP rules may be missing
2. **k3s CNI Configuration**: Flannel/CNI may not be routing external TCP correctly
3. **Tailscale Routing**: Tailscale may be intercepting pod traffic incorrectly
4. **Firewall Rules**: iptables or nftables blocking pod egress

### Workarounds Applied
1. ✅ Increased ArgoCD timeout from 15s to 300s
2. ✅ Rescheduled argocd-repo-server to k3s-node-0 (control plane with better connectivity)
3. ⚠️ Network policies verified (not the cause)

---

## 🔧 Required Fix (Future Work)

To enable ArgoCD GitOps automation, fix pod outbound connectivity:

### Option 1: Fix Outbound TCP Routing
```bash
# On each k3s node, verify iptables rules allow pod egress
sudo iptables -L -n -v | grep -A 5 "Chain FORWARD"

# Check k3s CNI configuration
cat /etc/cni/net.d/*.conflist

# Verify Tailscale is not interfering
sudo tailscale status
```

### Option 2: Use SSH for Git Access
Configure ArgoCD to use SSH instead of HTTPS:
```yaml
source:
  repoURL: git@github.com:ariel99gf/homelab.git  # Use SSH
```
Add SSH key to ArgoCD and GitHub.

### Option 3: Use Local Git Mirror
Host a Git mirror within the cluster using Gitea/Gogs.

### Option 4: Continue Manual Deployment
Apply manifests manually:
```bash
kubectl apply -k k8s/apps/prometheus/
kubectl apply -k k8s/apps/grafana/
# etc.
```

---

## 📊 Current State Summary

| Component | Status | Method | Notes |
|-----------|--------|--------|-------|
| **Git Repository** | ✅ Synced | Manual push | All changes in `develop` branch |
| **ArgoCD** | ✅ Installed | kubectl | Cannot reach GitHub |
| **App-of-Apps Manifest** | ✅ Created | kubectl apply | Sync blocked by network |
| **Monitoring Stack** | ✅ Running | Manual deployment | Fully operational |
| **GitOps Automation** | ❌ Blocked | N/A | Network issue prevents sync |

---

## 🎯 Next Steps

1. **Immediate:** Document network issue in homelab architecture docs
2. **Short-term:** Investigate Oracle Cloud security groups and k3s routing
3. **Medium-term:** Implement one of the workarounds above
4. **Long-term:** Establish fully automated GitOps pipeline

---

## 📝 Access Information

### ArgoCD UI Access
```bash
# Port forward to access UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### Grafana Access
```bash
# Port forward
kubectl port-forward -n grafana svc/grafana-service 3000:3000

# Access at http://localhost:3000
# Default credentials: admin/admin
```

---

**Status:** Phase 3 (GitOps Implementation) is 90% complete. Network fix required for full automation.
