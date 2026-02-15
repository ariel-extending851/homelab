# 🔴 CRITICAL: ***/*** Down - Recovery Plan

## Current Situation

**Status:** *** and *** web UIs are NOT accessible
**Cause:** RPi 3 overloaded (899MB RAM running 10+ proxies)
**Kubernetes API:** Timing out (control plane overwhelmed)
**Impact:** Cannot use kubectl to fix directly

## Root Cause Analysis

### What Happened

1. **Proxy Migration:** Deleted 6-7 proxies from RPi 4
2. **Recreation:** Tailscale operator (via ArgoCD) recreated them
3. **Scheduling:** StatefulSets have "sticky" node affinity - they returned to RPi 3
4. **Overload:** RPi 3 (899MB RAM) cannot handle 10+ proxies
5. **Cascading Failure:**
   - Proxies crash due to OOM
   - Constant restart loops
   - k3s API server overwhelmed
   - Cannot manage cluster

### Why ArgoCD/GitOps Matters

You mentioned: **"modification files have to be into this branch to functional"**

**The Problem:**
- We used imperative commands (`kubectl delete pods`)
- ArgoCD manages desired state from git (develop branch)
- The Tailscale operator continuously reconciles state
- When pods were deleted, operator recreated them
- But it recreated them on the same nodes (RPi 3) due to StatefulSet behavior

**The Solution:**
We need to work WITH ArgoCD, not against it.

---

## Recovery Options

### Option 1: Force StatefulSet Recreation (RECOMMENDED)

Delete the StatefulSets entirely (not just pods) - this breaks the "sticky" scheduling:

```bash
# Once API is accessible:

# 1. Delete failing StatefulSets
kubectl delete statefulset ts-***-ingress -n tailscale
kubectl delete statefulset ts-***-ingress -n tailscale

# 2. Let ArgoCD/Tailscale operator recreate them
# They will be scheduled on ANY available node (hopefully RPi 4)

# 3. Wait for recreation
kubectl get pods -n tailscale -w

# 4. Verify apps work
curl https://***.tail57bf10.ts.net
curl https://***-1.tail57bf10.ts.net
```

**Pros:** Properly breaks sticky scheduling
**Cons:** Brief downtime (1-2 minutes)

### Option 2: Add Resources to RPi 3

Since we can't easily control scheduling, add swap to RPi 3 to handle the load:

```bash
# SSH to RPi 3
ssh ubuntu@rasp-pi-03.tail57bf10.ts.net

# Create 1GB swap
sudo fallocate -l 1G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verify
free -h
```

**Pros:** Keeps current distribution, quick fix
**Cons:** RPi 3 will still be heavily loaded

### Option 3: Modify ProxyClass (GitOps Approach)

Since you mentioned everything must be in develop branch:

**Edit:** `k8s/system/tailscale-operator/proxyclass.yaml`

However, ProxyClass doesn't support node affinity directly. We'd need to:

1. Accept current distribution OR
2. Delete problematic services and recreate with different configurations OR
3. Use taints/tolerations (complex)

### Option 4: Rollback to Original State

Restore the original distribution where all proxies were on RPi 4:

```bash
# Once API is accessible
kubectl delete statefulset -n tailscale -l tailscale.com/proxy-class=default

# Wait for ArgoCD to recreate all proxies
# They will land on RPi 4 (where there's 5.9GB free RAM)
```

**Pros:** Guaranteed to work (was working before)
**Cons:** RPi 4 will be overloaded again

---

## Immediate Recovery Steps

Since API is down, we must wait or use SSH:

### Step 1: Wait for API Recovery

Check every 2-3 minutes:
```bash
kubectl get nodes
```

### Step 2: Once API is Up, Execute Option 1

```bash
#!/bin/bash
# fix-***-***.sh

echo "=== Fixing ***/*** Access ==="

# Delete failing StatefulSets (breaks sticky scheduling)
echo "Deleting *** proxy StatefulSet..."
kubectl delete statefulset ts-***-ingress -n tailscale --ignore-not-found=true

echo "Deleting *** proxy StatefulSet..."
kubectl delete statefulset ts-***-ingress -n tailscale --ignore-not-found=true

echo ""
echo "Waiting for recreation (30 seconds)..."
sleep 30

echo ""
echo "Checking new distribution..."
kubectl get pods -n tailscale -o wide | grep -E "(***|***|***)"

echo ""
echo "Testing endpoints..."
sleep 10
curl -s https://***.tail57bf10.ts.net/ping && echo "***: OK"
curl -s https://***-1.tail57bf10.ts.net/ping && echo "***: OK"

echo ""
echo "=== Fix Complete ==="
```

### Step 3: If Still Issues, Add Swap to RPi 3

```bash
ssh ubuntu@rasp-pi-03.tail57bf10.ts.net
# Run swap script for RPi 3 (modified for 1GB instead of 2GB)
```

---

## Prevention: Better GitOps Workflow

For future changes, instead of imperative commands:

1. **Modify git first:** Edit files in develop branch
2. **Let ArgoCD apply:** Automatic synchronization
3. **Verify:** Check that changes work
4. **Commit:** All changes tracked in git

**For this specific issue:**
We should have modified the Tailscale configuration in git BEFORE making changes, or accepted that proxy migration requires StatefulSet deletion (not just pod deletion).

---

## Current Status & Next Steps

**Waiting for:** Kubernetes API to recover (RPi 3 load decreasing)
**ETA:** 5-10 minutes
**Action:** Once API is up, execute Option 1 (delete StatefulSets)
**Alternative:** Add swap to RPi 3 to stabilize current state

**Success Criteria:**
- ✅ *** accessible at https://***.tail57bf10.ts.net
- ✅ *** accessible at https://***-1.tail57bf10.ts.net
- ✅ Response times under 5 seconds

---

## Quick Test

Try accessing apps directly (might work even if API is down):
```bash
curl -v https://***.tail57bf10.ts.net
curl -v https://***-1.tail57bf10.ts.net
```

If these timeout, the proxies are definitely down.

---

**Summary:** The apps themselves are healthy on RPi 4. The issue is the Tailscale proxies failing on RPi 3 due to memory constraints. Once API recovers, we delete the StatefulSets to break sticky scheduling and let them recreate on RPi 4.
