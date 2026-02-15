# RPi 4 Tailscale Proxy Audit & Optimization Plan

## Current State Analysis

### Tailscale Proxy Distribution (as of 2025-02-14)

#### rasp-pi-04 (RPi 4) - 9 PROXIES - **OVERLOADED** ⚠️

| Proxy | Target App | Target Node | Should Stay? | Reason |
|-------|-----------|-------------|--------------|---------|
| ts-***-ingress | *** | rasp-pi-04 | ✅ YES | Same node as app |
| ts-***-ingress | *** | rasp-pi-04 | ✅ YES | Same node as app |
| ts-***-ingress | *** | rasp-pi-04 | ✅ YES | Same node as app |
| ts-adguard-ingress | AdGuard | rasp-pi-03 | ❌ MOVE | App is on RPi 3 |
| ts-golink-ingress | GoLink | rasp-pi-03 | ❌ MOVE | App is on RPi 3 |
| ts-grafana-ingress | Grafana | k3s-server-1 | ❌ MOVE | App is on AWS |
| ts-loki-ingress | Loki | k3s-agent-2 | ❌ MOVE | App is on AWS |
| ts-prometheus-ingress | Prometheus | k3s-server-1 | ❌ MOVE | App is on AWS |
| ts-searxng-ingress | SearXNG | k3s-agent-2 | ❌ MOVE | App is on AWS |

**Current Impact on RPi 4:**
- 9 proxies × ~100MB RAM = ~900MB RAM consumed
- 9 proxies × CPU overhead = significant CPU cycles
- **Plus:** ***, ***, ***, ***, *** competing for resources

#### rasp-pi-03 (RPi 3) - 3 PROXIES

| Proxy | Target App | Target Node | Status |
|-------|-----------|-------------|--------|
| ts-***-ingress | *** | rasp-pi-04 | ⚠️ CROSS-NODE (inefficient) |
| ts-***-ingress | *** | rasp-pi-04 | ⚠️ CROSS-NODE (inefficient) |
| ts-***-ingress | *** | rasp-pi-04 | ⚠️ CROSS-NODE (inefficient) |

**Issue:** These 3 proxies should be on RPi 4 (where the apps are), not RPi 3.

#### k3s-server-1 (AWS) - 0 PROXIES - **UNDERUTILIZED**

Apps on this node:
- Grafana
- Prometheus
- ArgoCD
- CoreDNS

**Capacity:** Can host 3-4 proxies

#### k3s-agent-2 (AWS) - 0 PROXIES - **UNDERUTILIZED**

Apps on this node:
- Loki
- SearXNG
- ***

**Capacity:** Can host 3-4 proxies

---

## Optimization Strategy

### Phase 1: Move Cross-Node Proxies (Immediate - High Impact)

**Move these proxies OFF rasp-pi-04:**

1. **ts-adguard-ingress** → rasp-pi-03 (same node as AdGuard app)
2. **ts-golink-ingress** → rasp-pi-03 (same node as GoLink app)
3. **ts-grafana-ingress** → k3s-server-1 (same node as Grafana app)
4. **ts-loki-ingress** → k3s-agent-2 (same node as Loki app)
5. **ts-prometheus-ingress** → k3s-server-1 (same node as Prometheus app)
6. **ts-searxng-ingress** → k3s-agent-2 (same node as SearXNG app)

**Expected Result:**
- RPi 4 proxies: 9 → 3 (6 moved)
- RAM freed: ~600MB
- CPU load reduced

### Phase 2: Fix Proxies on Wrong Node (Immediate)

**Move these proxies TO rasp-pi-04:**

1. **ts-***-ingress** → rasp-pi-04 (*** is on RPi 4)
2. **ts-***-ingress** → rasp-pi-04 (*** is on RPi 4)

**Note:** ts-***-ingress on RPi 3 can stay or move - *** is on RPi 4, but keeping one proxy on RPi 3 is fine for balance.

---

## Target Distribution After Optimization

### rasp-pi-04 (RPi 4) - 5 PROXIES

| Proxy | Target App | Notes |
|-------|-----------|-------|
| ts-***-ingress | *** | Main download app |
| ts-***-ingress | *** | Movie management |
| ts-***-ingress | *** | Media server |
| ts-***-ingress | *** | Indexer manager |
| ts-***-ingress | *** | TV show management |

**Benefit:** All media-related proxies on same node as apps = efficient local traffic

### rasp-pi-03 (RPi 3) - 3 PROXIES

| Proxy | Target App | Notes |
|-------|-----------|-------|
| ts-adguard-ingress | AdGuard | DNS filtering |
| ts-golink-ingress | GoLink | URL shortener |
| ts-***-ingress-2 | *** | Backup/secondary (optional) |

### k3s-server-1 (AWS) - 2 PROXIES

| Proxy | Target App | Notes |
|-------|-----------|-------|
| ts-grafana-ingress | Grafana | Monitoring dashboard |
| ts-prometheus-ingress | Prometheus | Metrics collection |

### k3s-agent-2 (AWS) - 2 PROXIES

| Proxy | Target App | Notes |
|-------|-----------|-------|
| ts-loki-ingress | Loki | Log aggregation |
| ts-searxng-ingress | SearXNG | Search engine |

---

## Implementation Plan

### Step 1: Update ProxyClass Configuration

Current `proxyclass.yaml` has no nodeSelector - we need to add targeted nodeSelectors.

**BUT** - There's a problem: Tailscale Operator doesn't natively support per-proxy nodeSelectors via ProxyClass.

**Solution:** Use Kubernetes node affinity/tolerations OR redeploy proxies with specific node assignments.

### Step 2: Force Proxy Rescheduling

The easiest approach: **Delete proxies and let them recreate on better nodes**

```bash
# Delete proxies that should move OFF rasp-pi-04
kubectl delete pod -n tailscale ts-adguard-ingress-xxx-0
kubectl delete pod -n tailscale ts-golink-ingress-xxx-0
kubectl delete pod -n tailscale ts-grafana-ingress-xxx-0
kubectl delete pod -n tailscale ts-loki-ingress-xxx-0
kubectl delete pod -n tailscale ts-prometheus-ingress-xxx-0
kubectl delete pod -n tailscale ts-searxng-ingress-xxx-0

# Delete proxies that should move TO rasp-pi-04
kubectl delete pod -n tailscale ts-***-ingress-xxx-0
kubectl delete pod -n tailscale ts-***-ingress-xxx-0
```

**Risk:** New pods may land on same nodes if we don't control scheduling.

### Step 3: Control Scheduling with Node Affinity

Better approach: Add node affinity to Tailscale proxies using a custom solution.

Since Tailscale Operator doesn't support per-service node selectors, we have two options:

**Option A: Cordon RPi 4 temporarily**
```bash
# Cordon RPi 4 (prevents new pods from scheduling)
kubectl cordon rasp-pi-04

# Delete proxies that should move to AWS/RPi 3
kubectl delete pods -n tailscale -l tailscale.com/proxy-class=default

# Wait for them to recreate on other nodes
kubectl get pods -n tailscale -o wide

# Uncordon RPi 4
kubectl uncordon rasp-pi-04
```

**Option B: Use Pod Affinity (Advanced)**
Configure proxies to prefer nodes where their target apps are running.

**Option C: Manual StatefulSet Editing (Not Recommended)**
Edit each proxy StatefulSet directly (breaks GitOps).

**Recommendation: Use Option A (Cordon Method)**

---

## Detailed Execution Commands

### Pre-Flight Checks

```bash
# Document current state
echo "=== Current Proxy Distribution ==="
kubectl get pods -n tailscale -o wide | grep ingress

echo "=== RPi 4 Current Load ==="
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net "uptime && free -m"
```

### Execution Phase

```bash
#!/bin/bash
# optimize-proxies.sh

echo "=== RPi 4 Proxy Optimization ==="
echo "Step 1: Cordoning RPi 4 to force proxy migration..."
kubectl cordon rasp-pi-04

echo ""
echo "Step 2: Deleting proxies that should move off RPi 4..."
# These will recreate on other nodes
kubectl delete pod -n tailscale $(kubectl get pods -n tailscale -o name | grep -E "(adguard|golink|grafana|loki|prometheus|searxng)-ingress")

echo ""
echo "Step 3: Waiting for recreation..."
sleep 10
kubectl get pods -n tailscale -o wide

echo ""
echo "Step 4: Uncordoning RPi 4..."
kubectl uncordon rasp-pi-04

echo ""
echo "Step 5: Deleting proxies that should move TO RPi 4..."
# These are currently on wrong nodes
kubectl delete pod -n tailscale $(kubectl get pods -n tailscale -o name | grep -E "(***|***)-ingress")

echo ""
echo "Step 6: Final state..."
kubectl get pods -n tailscale -o wide

echo ""
echo "=== Optimization Complete ==="
```

### Post-Optimization Verification

```bash
# Check new distribution
echo "=== New Proxy Distribution ==="
kubectl get pods -n tailscale -o wide

# Check RPi 4 resource relief
echo "=== RPi 4 Load After Optimization ==="
ssh ubuntu@rasp-pi-04.tail57bf10.ts.net "uptime && free -m"

# Test all endpoints
echo "=== Testing Endpoints ==="
curl -s -o /dev/null -w "%{http_code}" https://grafana.tail57bf10.ts.net
# etc...
```

---

## Expected Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| RPi 4 Proxies | 9 | 5 | 44% reduction |
| RPi 4 RAM (proxies) | ~900MB | ~500MB | 400MB freed |
| Cross-node traffic | 6 proxies | 0 | 100% eliminated |
| RPi 4 Load Average | 4.0+ | 3.0-3.5 | 20-25% reduction |

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Proxies fail to reschedule | High | Cordon only one node at a time, verify each step |
| Apps temporarily unreachable | Medium | 30-60 sec downtime during proxy recreation |
| Wrong proxy distribution | Low | Verify with `kubectl get pods -o wide` after each step |
| RPi 3 overloaded | Low | Only moving 2 lightweight proxies to RPi 3 |

---

## Alternative: Manual Proxy Migration

If the cordon method doesn't work well, we can manually edit each service to use node affinity:

```yaml
# Example: Adding node affinity to a Tailscale service (not native)
# This would require a custom operator or webhook
```

**Note:** The cordon method is simplest and aligns with GitOps workflow.

---

## Next Steps

1. ✅ Review this audit
2. ✅ Approve the optimization plan
3. Execute the cordon-based migration
4. Verify results
5. Proceed to Phase 2: *arr app optimization

Ready to execute?
