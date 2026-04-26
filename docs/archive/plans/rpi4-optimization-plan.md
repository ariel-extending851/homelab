# RPi 4 Optimization Plan

## Executive Summary

**Goal:** Optimize RPi 4 performance by:
1. Moving Tailscale proxies to AWS nodes
2. Reducing *arr app resource consumption
3. System-level optimizations

**Expected Outcome:** 30-50% performance improvement without workload migration.

---

## Current RPi 4 Workload (rasp-pi-04)

### Running Applications

| App | CPU Limit | Memory | Impact |
|-----|-----------|---------|---------|
| Tailscale Proxies (6x) | Shared | ~100MB each | Medium |

**Total Load:** Severely overloaded

### Problem Analysis

**Primary Bottlenecks:**
1. **6 Tailscale proxies** consuming CPU/memory for ingress
4. **Swap thrashing** due to memory pressure

---

## Optimization Strategy

### Phase 1: Move Tailscale Proxies to AWS (High Impact)

**Current Distribution:**
- rasp-pi-04: 6 proxies (overloaded)
- rasp-pi-03: 5 proxies (acceptable)
- AWS nodes: 3 proxies (underutilized)

**Target Distribution:**
- rasp-pi-04: 2-3 proxies (only *arr apps)
- rasp-pi-03: 4-5 proxies (lightweight apps)
- AWS nodes: 7-8 proxies (more capacity)

**Apps to Move Off RPi 4:**
1. Grafana proxy → AWS
2. Prometheus proxy → AWS
3. Loki proxy → AWS
4. SearXNG proxy → AWS
5. Possibly others

**Result:** Free up ~600MB RAM + CPU cycles on RPi 4

### Phase 2: Optimize *arr App Settings (Medium Impact)

**Disable Unnecessary Features:**
```
Settings → Media Management → File Management:
- [ ] Automatically rename episodes (reduces disk I/O)
- [ ] Create empty series folders (disable)

Settings → Profiles:
- Reduce quality profiles (fewer options = less CPU)
- Disable "Upgrades Allowed" if not needed

Settings → Indexers:
- Increase RSS Sync Interval: 15 → 30 minutes
- Disable automatic search for old episodes

Settings → Connect:
- Disable unused notifications

Tasks (System → Tasks):
- Refresh Series: Daily → Weekly
- Refresh Monitored Downloads: Every minute → Every 5 minutes
- Housekeeping: Daily → Weekly
```

**Database Maintenance:**
```bash

# Vacuum database (reduces size, improves performance)
cd /config
```

```
Settings → Media Management:
- [ ] Automatically rename movies (disable if not needed)

Settings → Tasks:
- Refresh Movie: Daily → Weekly
- Update Movie Info: Hourly → Daily
```

```
Settings → Indexers:
- Increase sync interval: 15 → 60 minutes
- Disable unused indexers

Settings → Apps:
- Remove unused app connections
- Sync interval: 5 → 60 minutes
```

### Phase 3: System-Level Optimizations (Medium Impact)

#### 1. Increase Swap Space

Current RPi 4 likely has default 100MB swap. Increase to 2GB:

```bash
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net

# Check current swap
free -h
swapon -s

# Create 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verify
free -h
```

#### 2. CPU Governor Optimization

Ensure CPU runs at max frequency:

```bash
# Check current governor
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Set to performance (requires root)
echo 'performance' | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Make permanent
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils
sudo systemctl enable cpufrequtils
```

#### 3. I/O Scheduler Optimization

For USB3 SSD (if using):

```bash
# Check current scheduler
cat /sys/block/sda/queue/scheduler

# Set to mq-deadline or kyber
echo 'mq-deadline' | sudo tee /sys/block/sda/queue/scheduler
```

#### 4. Reduce Journal Logging

```bash
# Reduce systemd journal size
sudo systemctl edit systemd-journald

# Add:
[Journal]
SystemMaxUse=100M
MaxFileSec=1week
```

#### 5. Docker/K3s Optimizations

```bash
# Edit k3s config
sudo nano /etc/rancher/k3s/config.yaml

# Add resource limits for k3s-agent
kubelet-arg:
  - "eviction-hard=memory.available<100Mi"
  - "eviction-soft=memory.available<200Mi"
  - "eviction-soft-grace-period=memory.available=1m"
  - "system-reserved=cpu=100m,memory=200Mi"
  - "kube-reserved=cpu=100m,memory=200Mi"
```

### Phase 4: Resource Limits Tuning

#### Review Current Limits

```yaml
resources:
  limits:
    cpu: 2000m
    memory: 1Gi
  requests:
    cpu: 100m
    memory: 256Mi
```

**Issue:** 2000m limit allows CPU hogging

**Better Approach:**
```yaml
resources:
  limits:
    cpu: 1500m  # Slightly reduced
    memory: 512Mi  # Reduced if not using large libraries
  requests:
    cpu: 100m
    memory: 256Mi
```

**Add Priority Classes:**
```yaml

priorityClassName: medium-priority  # For *arr apps
```

---

## Implementation Order

### Immediate (Today)
1. ✅ Document current state (this file)
2. Move 3-4 Tailscale proxies from RPi 4 to AWS
3. Increase swap to 2GB

### Short Term (This Week)

### Medium Term (Next Week)
7. Vacuum databases
8. Tune CPU governor
9. Monitor and adjust

---

## Expected Results

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| RPi 4 Load Average | 4.0+ | 2.0-2.5 | 40-50% |
| Available RAM | <500MB | 1-1.5GB | 2-3x |

---

## Rollback Plan

If any optimization causes issues:

1. **Tailscale issues:** Edit ProxyClass, move proxies back
2. **App crashes:** Revert settings changes, restart pod
3. **System instability:** Remove swap file, revert CPU governor

---

## Monitoring

Track improvements with:

```bash
# RPi 4 system metrics
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net "uptime && free -m && top -bn1 | head -20"

# Pod resource usage

# Response times
```

---

## Next Steps

1. **Review this plan**
2. **Decide which Tailscale proxies to move first**
3. **Execute Phase 1** (proxies + swap)
4. **Measure results** before proceeding

Ready to start?
