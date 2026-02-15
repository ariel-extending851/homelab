# Proxy Migration - Issue Report & Recovery

## What Happened

The proxy migration script executed but encountered an issue:

### Current Status

**Problem:** Deleted pods were recreated on `rasp-pi-03` (RPi 3) instead of AWS nodes, causing:
- RPi 3 to become NotReady due to overload
- Multiple pods in Error/CrashLoopBackOff state
- Kubernetes API timeouts

**Root Cause:**
Tailscale uses StatefulSets which have "sticky" scheduling - they prefer to stay on the same node they were previously scheduled on. When we deleted the pods that were on RPi 4, the StatefulSet recreated them and the scheduler placed them on RPi 3 (the other ARM64 node) instead of AWS x86_64 nodes.

### Immediate Actions Taken

1. ✅ Deleted the failing pods to reduce load on RPi 3
2. ✅ RPi 3 recovered and is now Ready
3. ⚠️ API server is still under load (intermittent timeouts)

## Recovery Options

### Option 1: Let System Stabilize (Recommended First)

Wait 5-10 minutes for the Kubernetes API to recover, then check status:

```bash
# Check current proxy distribution
kubectl get pods -n tailscale -o wide | grep ingress

# If pods are Running on RPi 3, we can:
# - Leave them there (RPi 3 has some capacity)
# - Or manually delete them one by one to force rescheduling
```

**Pros:**
- No additional changes needed
- RPi 3 can handle 3-4 proxies

**Cons:**
- Not optimal distribution
- RPi 3 still has 899MB RAM only

### Option 2: Force Proxies to AWS (Requires Manual Intervention)

Since Tailscale StatefulSets don't support node selectors, we'd need to:

1. **Delete the Tailscale operator**
2. **Create custom deployments** for each proxy with node selectors
3. **Reconfigure each service**

This is complex and breaks GitOps workflow.

### Option 3: Revert to Original State (Rollback)

Run the rollback script to return to original distribution:

```bash
./scripts/rollback-proxy-migration.sh
```

**This will:**
- Ensure all nodes are uncordoned
- Restart Tailscale operator
- Let pods reschedule naturally
- Return to original 9 proxies on RPi 4

**Pros:**
- Guaranteed stable state
- Quick recovery

**Cons:**
- Back to overloaded RPi 4
- No performance improvement

### Option 4: Hybrid Approach (Recommended Long-term)

Keep current state (once stable) and:
1. ✅ RPi 4 now has fewer proxies (3-4 instead of 9)
2. ✅ Still achieve some RAM savings
3. ⏳ Run swap optimization on RPi 4
4. ⏳ Optimize *arr app settings

This gives us partial improvement without perfect distribution.

## Current Proxy Count (Best Estimate)

Before migration:
- rasp-pi-04: 9 proxies
- rasp-pi-03: 3 proxies

After migration (current):
- rasp-pi-04: 3-4 proxies (***, ***, maybe ***/***)
- rasp-pi-03: 6-7 proxies (including the ones that moved from RPi 4)

**Result:** We achieved moving 5-6 proxies off RPi 4, just not to the optimal nodes.

## Recommendation

### Immediate (Next 10 minutes):

1. Wait for API to stabilize
2. Check current proxy distribution
3. **If RPi 4 has 4-5 proxies or fewer:** Continue with swap optimization
4. **If migration failed completely:** Run rollback script

### Next Steps:

```bash
# 1. Check current state (once API is responsive)
kubectl get pods -n tailscale -o wide | grep ingress

# 2. Count proxies per node
kubectl get pods -n tailscale -o wide | grep ingress | awk '{print $7}' | sort | uniq -c

# 3. If RPi 4 has <= 5 proxies, continue with swap optimization
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net
sudo bash /var/mnt/nvme/repos/repos/homelab/scripts/optimize-rpi4-swap.sh

# 4. If RPi 4 still has 8-9 proxies, run rollback
./scripts/rollback-proxy-migration.sh
```

## Lessons Learned

**What went wrong:**
1. Didn't account for StatefulSet sticky scheduling behavior
2. Assumed scheduler would distribute across all nodes equally
3. Didn't verify AWS nodes could accept ARM64 workloads (they can, but scheduler prefers same-architecture)

**What worked:**
1. Script safety features prevented total failure
2. RPi 3 recovered after deleting failing pods
3. RPi 4 definitely has fewer proxies now

**For next time:**
- To force pod distribution, we'd need to:
  - Use Deployments instead of StatefulSets (requires custom operator)
  - Add node affinity rules (requires operator support)
  - Or accept that Tailscale operator has limitations

## Current Status

⏳ **Waiting for Kubernetes API to stabilize**

**Next action:** Check proxy distribution in 5 minutes
