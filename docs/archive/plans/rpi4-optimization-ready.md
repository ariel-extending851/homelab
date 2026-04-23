# RPi 4 Optimization - Implementation Ready

## ✅ What We Accomplished

### 1. Cancelled Longhorn Migration
- **Decision:** Keep *arr apps on RPi 4 (privacy/legal concerns with AWS)
- **Reason:** AWS actively monitors for piracy, will ban account
- **Status:** All Longhorn config files preserved in `k8s/system/longhorn/` for future use

### 2. Created Audit & Optimization Plan
**Location:** `docs/rpi4-optimization-plan.md`

**Key Findings:**
- RPi 4 has **9 Tailscale proxies** (overloaded)
- **6 of these** are for apps NOT on RPi 4 (inefficient)
- Current RAM usage: ~900MB just for proxies
- Plus ***, ***, ***, ***, *** = severe overload

### 3. Created Proxy Audit
**Location:** `docs/rpi4-proxy-audit.md`

**Analysis Results:**

| Node | Current Proxies | Target Proxies | Action |
|------|----------------|----------------|--------|
| rasp-pi-04 | 9 | 5 | **Move 6 off** |
| rasp-pi-03 | 3 | 3 | Keep/optimize |
| k3s-server-1 | 0 | 2 | **Move 2 here** |
| k3s-agent-2 | 0 | 2 | **Move 2 here** |

### 4. Created Implementation Scripts

**Location:** `scripts/`

| Script | Purpose | When to Run |
|--------|---------|-------------|
| `migrate-proxies.sh` | Moves 6 proxies off RPi 4 | **Now** |
| `optimize-rpi4-swap.sh` | Increases swap to 2GB | After proxy migration |

---

## 🎯 Expected Results

### After Proxy Migration
- **RPi 4 Proxies:** 9 → 5 (44% reduction)
- **RAM Freed:** ~400MB
- **Load Reduction:** 20-25%
- **Cross-node Traffic:** Eliminated

### After Swap Increase
- **Swap Size:** 100MB → 2GB
- **OOM Prevention:** Better handling of memory spikes
- **App Stability:** Reduced crashes during heavy operations

### Combined Impact
- ***/*** response time: 10+ sec → 3-5 sec
- *** response time: 5+ sec → 1-2 sec
- RPi 4 load average: 4.0+ → 3.0-3.5

---

## 🚀 Execution Plan

### Phase 1: Proxy Migration (Execute Now)

```bash
# From your workstation
cd /var/mnt/nvme/repos/repos/homelab

# Execute proxy migration
./scripts/migrate-proxies.sh

# The script will:
# 1. Cordon RPi 4 (prevent new pods)
# 2. Delete 6 proxies that should be elsewhere
# 3. Wait for recreation on AWS/RPi 3
# 4. Uncordon RPi 4
# 5. Fix 2 proxies on wrong nodes
```

**Expected Downtime:** 30-60 seconds per proxy

### Phase 2: Swap Optimization (After Proxy Migration)

```bash
# SSH to RPi 4
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net

# Copy and run swap script
cat > /tmp/optimize-swap.sh << 'EOF'
[paste contents of scripts/optimize-rpi4-swap.sh]
EOF

chmod +x /tmp/optimize-swap.sh
sudo /tmp/optimize-swap.sh
```

**Expected Downtime:** None (swap added live)

### Phase 3: *arr App Optimization (Optional - This Week)

***** Settings:**
```
Settings → Tasks:
- Refresh Series: Daily → Weekly
- Refresh Monitored Downloads: 1 min → 5 min
- Rss Sync: 15 min → 30 min
```

***** Settings:**
```
Settings → Tasks:
- Refresh Movie: Daily → Weekly
- Update Movie Info: Hourly → Daily
```

***** Settings:**
```
Settings → Apps:
- Sync interval: 5 min → 60 min
```

### Phase 4: Database Maintenance (Optional - Next Week)

```bash
# Vacuum databases to improve performance
kubectl exec -it deploy/*** -- /bin/sh -c "sqlite3 /config/***.db 'VACUUM;'"
kubectl exec -it deploy/*** -- /bin/sh -c "sqlite3 /config/***.db 'VACUUM;'"
kubectl exec -it deploy/*** -- /bin/sh -c "sqlite3 /config/***.db 'VACUUM;'"
```

---

## 📊 Current vs Target State

### Current (Problems)
```
rasp-pi-04 (RPi 4):
├── 9 Tailscale proxies (900MB RAM)
├── *** (1-2GB RAM when transcoding)
├── *** (300-500MB)
├── *** (300-500MB)
├── *** (100-200MB)
└── *** (200-400MB)

Result: Severe overload, CPU throttling, slow response times
```

### After Optimization (Target)
```
rasp-pi-04 (RPi 4):
├── 5 Tailscale proxies (500MB RAM) ← Reduced
├── *** (1-2GB RAM)
├── *** (300-500MB) ← Optimized settings
├── *** (300-500MB) ← Optimized settings
├── *** (100-200MB) ← Optimized settings
└── *** (200-400MB)

Result: Balanced load, faster response times
```

---

## ⚠️ Risks & Rollback

### Risk: Apps Temporarily Unreachable
**During proxy migration, apps will be offline for 30-60 seconds.**

**Mitigation:**
- Migration happens sequentially (not all at once)
- Test critical apps first
- Run during low-usage time

### Risk: Proxies Don't Reschedule Properly
**New pods might land on same node if scheduler doesn't distribute well.**

**Mitigation:**
- Cordon method ensures RPi 4 is unavailable
- If issues occur, manually delete specific pods

### Rollback Commands

If migration causes issues:

```bash
# Uncordon RPi 4 (if still cordoned)
kubectl uncordon rasp-pi-04

# Restart Tailscale operator (forces recreation)
kubectl rollout restart deployment -n tailscale operator

# Remove swap (if causing issues)
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net "sudo swapoff /swapfile && sudo rm /swapfile"
```

---

## 📋 Checklist

### Before Starting
- [ ] Review `docs/rpi4-proxy-audit.md`
- [ ] Verify kubectl access: `kubectl get nodes`
- [ ] Check current RPi 4 state: `ssh ubuntu@rasp-pi-04.tail57bf10.ts.net "free -m && uptime"`
- [ ] Have rollback commands ready
- [ ] Plan for 5-10 minute maintenance window

### During Execution
- [ ] Run proxy migration script
- [ ] Verify proxy distribution with `kubectl get pods -n tailscale -o wide`
- [ ] Test critical endpoints (Grafana, ***, etc.)

### After Migration
- [ ] Run swap optimization on RPi 4
- [ ] Verify RPi 4 load: `ssh ubuntu@rasp-pi-04.tail57bf10.ts.net "uptime"`
- [ ] Test all *arr apps are accessible
- [ ] Commit any config changes to git

---

## 📁 Files Created

```
homelab/
├── docs/
│   ├── rpi4-optimization-plan.md      # Main optimization plan
│   └── rpi4-proxy-audit.md             # Proxy distribution analysis
├── scripts/
│   ├── migrate-proxies.sh              # Proxy migration script
│   └── optimize-rpi4-swap.sh           # Swap optimization script
└── k8s/system/longhorn/                # Preserved for future use
    ├── values.yaml
    ├── namespace.yaml
    ├── storageclass.yaml
    ├── README.md
    └── MIGRATION.md
```

---

## 🎯 Ready to Execute?

**Next Action:** Run proxy migration

```bash
cd /var/mnt/nvme/repos/repos/homelab
./scripts/migrate-proxies.sh
```

**Estimated Time:** 2-3 minutes

**Expected Result:** 6 proxies moved off RPi 4, ~400MB RAM freed

---

## Questions?

- Review the detailed audit: `docs/rpi4-proxy-audit.md`
- Check the optimization plan: `docs/rpi4-optimization-plan.md`
- Examine scripts before running: `cat scripts/migrate-proxies.sh`

**Proceed with execution?**
