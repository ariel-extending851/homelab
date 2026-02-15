# Longhorn Storage Deployment Guide

## Overview

This directory contains the configuration for deploying Longhorn distributed block storage system to the homelab cluster. Longhorn provides replicated persistent volumes without the operational overhead of traditional storage clusters.

## Architecture Decision

**Why Longhorn over NFS?**
- Native Kubernetes integration with CSI driver
- Built-in replication for data redundancy
- Automated volume snapshots and backups
- Block storage (better for databases/media apps)
- Works across mixed architecture (ARM64 + x86_64)
- No single point of failure (distributed)

## Prerequisites

### Node Requirements

| Node | RAM | Architecture | Longhorn Role | Status |
|------|-----|-------------|---------------|---------|
| k3s-server-1 | 2 GB | x86_64 (AWS) | Storage + Manager | ✅ Eligible |
| k3s-agent-2 | 2 GB | x86_64 (AWS) | Storage + Manager | ✅ Eligible |
| rasp-pi-04 | 7.6 GB | ARM64 | Storage + Manager | ✅ Eligible |
| rasp-pi-03 | 899 MB | ARM64 | **Excluded** | ❌ Insufficient RAM |

**Note:** RPi 3 is intentionally excluded due to Longhorn's minimum 2GB RAM requirement.

### Required Software

All eligible nodes must have `open-iscsi` installed:

```bash
# Run on EACH node (not from your workstation)
./install-prerequisites.sh

# Or manually:
# Ubuntu/Debian:
sudo apt-get update && sudo apt-get install -y open-iscsi
sudo systemctl enable --now iscsid

# RHEL/CentOS/Fedora:
sudo dnf install -y iscsi-initiator-utils
sudo systemctl enable --now iscsid
```

## Installation Steps

### Step 1: Label Nodes

Run from your workstation with kubectl access:

```bash
# Label eligible nodes for Longhorn storage
kubectl label nodes k3s-server-1 hl-storage-capable=true --overwrite
kubectl label nodes k3s-agent-2 hl-storage-capable=true --overwrite
kubectl label nodes rasp-pi-04 hl-storage-capable=true --overwrite

# Verify (rasp-pi-03 should NOT have the label)
kubectl get nodes -L hl-storage-capable
```

Or use the provided script:

```bash
./label-nodes.sh
```

### Step 2: Deploy via ArgoCD

```bash
# Apply the ArgoCD Application
kubectl apply -f ../argocd/longhorn-app.yaml

# Watch the deployment
kubectl get pods -n hl-longhorn -w
```

### Step 3: Verify Installation

```bash
# Check Longhorn manager pods
kubectl get pods -n hl-longhorn

# Check storage classes
kubectl get storageclass

# Check Longhorn UI (port-forward)
kubectl port-forward -n hl-longhorn svc/longhorn-frontend 8080:80
# Access at http://localhost:8080
```

## Configuration Details

### Resource Limits

Given the memory-constrained AWS nodes (2GB each), conservative limits are set:

| Component | Request | Limit |
|-----------|---------|-------|
| Longhorn Manager | 128Mi | 512Mi |
| Longhorn Driver | 64Mi | 256Mi |
| Instance Manager | 128Mi | 1024Mi |
| Longhorn UI | 64Mi | 256Mi |

### Replica Configuration

- **Default Replica Count:** 2 (not 3) to balance reliability vs resource usage
- **Eligible Nodes:** 3 (2 AWS + 1 RPi 4)
- **Minimum Available:** 25% free space threshold

### StorageClass

Name: `hl-longhorn`

Features:
- Volume expansion enabled
- Retain reclaim policy (data preserved on PVC deletion)
- WaitForFirstConsumer binding mode (optimal scheduling)
- Best-effort data locality
- 2 replicas for redundancy

## Post-Installation: Application Migration

### Migration Order

1. ******* (lowest risk - no active downloads)
2. ******* (medium risk - TV show metadata)
3. ******* (medium risk - movie metadata)

See `MIGRATION.md` for detailed migration procedures.

### Quick Migration Command

```bash
# Backup existing PVC data first!
./scripts/backup-pvc.sh ***-config
./scripts/backup-pvc.sh ***-config
./scripts/backup-pvc.sh ***-config

# Update deployments to use new StorageClass
kubectl patch pvc ***-config -p '{"spec":{"storageClassName":"hl-longhorn"}}'
```

## Monitoring

Longhorn exposes Prometheus metrics at `:9500/metrics` on each manager pod.

ServiceMonitor is enabled for Prometheus Operator integration.

## Troubleshooting

### Issue: Pods stuck in Pending

**Cause:** Node not labeled with `hl-storage-capable=true`

**Fix:**
```bash
kubectl label nodes <node-name> hl-storage-capable=true
```

### Issue: Volume not attaching

**Cause:** open-iscsi not installed on node

**Fix:**
```bash
# On the affected node
sudo apt-get install -y open-iscsi
sudo systemctl enable --now iscsid
```

### Issue: High memory usage

**Cause:** AWS nodes at memory limit

**Fix:** Scale down replica count:
```bash
kubectl -n hl-longhorn edit settings.longhorn.io default-replica-count
# Change to 1 (less redundancy but lower resource usage)
```

### Issue: RPi 3 showing in Longhorn UI

**Cause:** Node label not properly excluded

**Fix:** Ensure RPi 3 does NOT have `hl-storage-capable` label:
```bash
kubectl label nodes rasp-pi-03 hl-storage-capable-  # Remove label if present
```

## Rollback Plan

If issues occur:

1. Scale down Longhorn:
   ```bash
   kubectl scale deployment -n hl-longhorn --all --replicas=0
   ```

2. Switch apps back to local-path storage

3. Delete Longhorn namespace:
   ```bash
   kubectl delete namespace hl-longhorn
   ```

## References

- [Longhorn Documentation](https://longhorn.io/docs/1.6.0/)
- [Longhorn on ARM64](https://longhorn.io/docs/1.6.0/deploy/install/#installation-requirements)
- [Helm Values Reference](https://github.com/longhorn/longhorn/blob/master/chart/values.yaml)

## Cost Impact

Longhorn adds minimal cost:
- Uses existing node storage (no additional cloud storage)
- CPU/Memory overhead: ~500MB RAM total across cluster
- Network overhead: Minimal for homelab workloads
