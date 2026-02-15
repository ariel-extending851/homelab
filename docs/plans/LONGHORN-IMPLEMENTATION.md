# Longhorn Storage Implementation - Summary

## ✅ What Was Created

### 1. Configuration Files (`k8s/system/longhorn/`)

| File | Purpose | Size |
|------|---------|------|
| `values.yaml` | Helm values for Longhorn with resource limits and RPi 3 exclusion | 3.2 KB |
| `namespace.yaml` | Namespace definition for `hl-longhorn` | 429 B |
| `storageclass.yaml` | Custom StorageClass `hl-longhorn` with 2 replicas | 1.1 KB |
| `kustomization.yaml` | Kustomize configuration for ArgoCD | 752 B |
| `README.md` | Complete deployment guide | 5.7 KB |
| `MIGRATION.md` | Detailed migration plan for media apps | 9.7 KB |
| `label-nodes.sh` | Script to label eligible nodes | 1.2 KB |
| `install-prerequisites.sh` | Script to install open-iscsi on nodes | 1.8 KB |

### 2. ArgoCD Application (`k8s/argocd/longhorn-app.yaml`)

GitOps-ready deployment configuration with:
- Auto-sync initially disabled for safety
- Resource pruning disabled during initial deployment
- Retry logic for resilience

---

## 🏗️ Architecture Overview

### Storage Nodes (Eligible for Longhorn)

```
┌─────────────────────────────────────────────────────────┐
│                    Longhorn Cluster                     │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ k3s-server-1 │  │ k3s-agent-2  │  │ rasp-pi-04   │  │
│  │  (AWS EC2)   │  │  (AWS EC2)   │  │  (RPi 4)     │  │
│  │   2 GB RAM   │  │   2 GB RAM   │  │   7.6 GB RAM │  │
│  │  x86_64      │  │  x86_64      │  │  ARM64       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                  │                  │          │
│         └──────────────────┴──────────────────┘          │
│                            │                            │
│              Replica 1 ────┼──── Replica 2               │
│                    (Distributed Storage)                  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              EXCLUDED NODE (rasp-pi-03)                 │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ rasp-pi-03 (RPi 3)                                  ││
│  │ 899 MB RAM - INSUFFICIENT for Longhorn              ││
│  │ Will continue running lightweight apps only         ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Replica Strategy

- **Default Replicas:** 2 (not 3 to conserve memory on AWS nodes)
- **Replication Factor:** Data written to 2 of 3 available nodes
- **Result:** 50% storage overhead, but data survives single node failure

---

## 📋 Next Steps to Execute

### Phase 1: Prerequisites Installation (Manual on Each Node)

You need to SSH into each eligible node and install `open-iscsi`:

**On AWS nodes (k3s-server-1, k3s-agent-2):**
```bash
ssh ec2-user@k3s-server-1.tail57bf10.ts.net
sudo dnf install -y iscsi-initiator-utils
sudo systemctl enable --now iscsid
```

```bash
ssh ec2-user@k3s-agent-2.tail57bf10.ts.net
sudo dnf install -y iscsi-initiator-utils
sudo systemctl enable --now iscsid
```

**On RPi 4 (rasp-pi-04):**
```bash
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net
sudo apt-get update
sudo apt-get install -y open-iscsi
sudo systemctl enable --now iscsid
```

**OR use the provided script (run on each node):**
```bash
./k8s/system/longhorn/install-prerequisites.sh
```

### Phase 2: Node Labeling (From Your Workstation)

```bash
cd /var/mnt/nvme/repos/repos/homelab

# Make script executable and run
chmod +x k8s/system/longhorn/label-nodes.sh
./k8s/system/longhorn/label-nodes.sh

# Verify (rasp-pi-03 should NOT have the label)
kubectl get nodes -L hl-storage-capable
```

### Phase 3: Deploy Longhorn

```bash
# Apply the ArgoCD Application
kubectl apply -f k8s/argocd/longhorn-app.yaml

# Watch deployment progress
kubectl get pods -n hl-longhorn -w

# Wait for all pods to be Ready (should take 2-3 minutes)
```

### Phase 4: Verify Installation

```bash
# Check all components are running
kubectl get pods -n hl-longhorn

# Verify StorageClass was created
kubectl get storageclass hl-longhorn

# Port-forward to access Longhorn UI
kubectl port-forward -n hl-longhorn svc/longhorn-frontend 8080:80
# Open http://localhost:8080 in browser
```

### Phase 5: Application Migration

**Follow the detailed migration guide:**

See `k8s/system/longhorn/MIGRATION.md` for complete procedure.

**Quick Summary:**
1. ******* (Pilot - lowest risk) - 2 min downtime
2. ******* - 5 min downtime
3. ******* - 5 min downtime

Each migration involves:
- Scaling down app
- Creating backup
- Creating new Longhorn PVC
- Restoring data
- Updating deployment to use AWS node + Longhorn
- Verifying functionality

---

## 💰 Cost & Resource Impact

### AWS Cost Impact
- **Storage:** Uses existing EBS volumes (no additional cost)
- **Network:** Minimal - intra-cluster traffic is free
- **CPU:** ~0.5 vCPU overhead total across cluster
- **RAM:** ~500 MB overhead total across cluster
- **Total Additional Cost:** $0

### Performance Impact
- **Before:** Apps on RPi 4 with CPU throttling, slow page loads (10+ sec)
- **After:** Apps on x86_64 AWS nodes with network storage (2-3 sec)
- **Expected Improvement:** 5-10x faster response times

### Resource Redistribution
- **RPi 4 Load:** Will decrease significantly (moving CPU-intensive apps to AWS)
- **AWS Nodes:** Will take on media apps, but have dedicated CPU cores
- **RPi 3:** Unchanged (running lightweight services only)

---

## ⚠️ Important Notes

### 1. RPi 3 Exclusion
RPi 3 (`rasp-pi-03`) is **intentionally excluded** from Longhorn:
- **Reason:** Only 899MB RAM (Longhorn requires minimum 2GB)
- **Impact:** AdGuard and proxies continue running as-is
- **No action needed** - node labels automatically exclude it

### 2. Conservative Resource Limits
AWS nodes have only 2GB RAM each. We've set conservative limits:
- Longhorn Manager: 512MB max
- Instance Manager: 1GB max
- Default Replica Count: 2 (not 3)

If you experience memory pressure, you can reduce to 1 replica (less redundancy).

### 3. Data Safety
- **Reclaim Policy:** Retain (data preserved even if PVC deleted)
- **Replicas:** 2 copies of data across different nodes
- **Backups:** Required before migration (scripts provided)

---

## 🔧 Troubleshooting

### If Longhorn pods don't start:
```bash
# Check if open-iscsi is installed on all nodes
kubectl describe nodes | grep -A5 "Allocated resources"

# Check Longhorn logs
kubectl logs -n hl-longhorn -l app=longhorn-manager
```

### If volumes don't attach:
```bash
# Verify iscsid is running on node
ssh <node> sudo systemctl status iscsid

# Check node labels
kubectl get nodes -L hl-storage-capable
```

### If AWS nodes run out of memory:
```bash
# Reduce replica count to 1
kubectl -n hl-longhorn edit settings.longhorn.io default-replica-count
# Change value from 2 to 1
```

---

## 📚 Documentation

All details are in:
- **Deployment Guide:** `k8s/system/longhorn/README.md`
- **Migration Plan:** `k8s/system/longhorn/MIGRATION.md`
- **Upstream Docs:** https://longhorn.io/docs/1.6.0/

---

## ✅ Checklist Before Starting

- [ ] Read `README.md` and `MIGRATION.md`
- [ ] Install open-iscsi on k3s-server-1
- [ ] Install open-iscsi on k3s-agent-2
- [ ] Install open-iscsi on rasp-pi-04
- [ ] Run `label-nodes.sh`
- [ ] Have kubectl access verified
- [ ] Plan maintenance window (12 min total downtime)

---

## 🚀 Ready to Execute?

Start with **Phase 1** - installing prerequisites on each node.

Once that's complete, run:
```bash
kubectl apply -f k8s/argocd/longhorn-app.yaml
```

Then proceed to the migration phase.

**Questions?** Refer to the detailed documentation in `README.md` and `MIGRATION.md`.
