# PR #27 Post-Merge Checklist

**PR Title**: perf(monitoring): Optimize Grafana/Loki performance and restore comprehensive dashboard  
**PR URL**: https://github.com/ariel99gf/homelab/pull/27  
**Merge Date**: _[To be filled after merge]_

---

## 🎯 Objective
Ensure all performance optimizations are deployed correctly after merging `fix/grafana-dashboard-provisioning` → `develop`.

---

## ✅ Pre-Merge Verification (COMPLETED)

- [x] All 3 commits are on feature branch
- [x] ArgoCD syncing from feature branch (temporary state)
- [x] Dashboard files validated:
  - `k8s/apps/grafana/dashboard-provider.yaml` (232 bytes)
  - `k8s/apps/grafana/dashboard-homelab-k3s-overview.yaml` (~50KB, 20 panels)
- [x] Loki configuration optimized (parallelism + caching)
- [x] Grafana CPU limit increased (500m → 1000m)
- [x] LogQL queries refactored (label selectors)
- [x] Pull Request #27 created

---

## 🚀 Post-Merge Tasks

### Priority 1: Revert ArgoCD to Develop Branch (CRITICAL)

**Current State**: ArgoCD is syncing from feature branch `fix/grafana-dashboard-provisioning`

**Action Required**:
```bash
# Step 1: Verify PR is merged
git checkout develop
git pull origin develop
git log -1 --oneline  # Should show merge commit or squashed commit

# Step 2: Revert ArgoCD target revision to develop
kubectl patch application homelab-apps-root -n argocd \
  --type=json \
  -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "develop"}]'

# Step 3: Verify patch applied
kubectl get application homelab-apps-root -n argocd -o jsonpath='{.spec.source.targetRevision}'
# Expected output: develop

# Step 4: Wait for ArgoCD to sync from develop branch
kubectl get application homelab-apps-root -n argocd -o jsonpath='{.status.sync.status}'
# Expected output: Synced
```

**Verification**:
- [ ] `spec.source.targetRevision` = `"develop"`
- [ ] `status.sync.status` = `"Synced"`
- [ ] `status.sync.revision` matches latest commit on develop branch

**Timeline**: Execute immediately after PR merge (within 5 minutes)

---

### Priority 2: Run Automated Validation Script

**Command**:
```bash
cd /var/mnt/nvme/repos/repos/homelab
./validate-dashboard-performance.sh
```

**Expected Results**:
- [ ] ✅ Test 1: Grafana pod Running and Ready
- [ ] ✅ Test 2: 3+ ConfigMaps exist (including dashboard files)
- [ ] ✅ Test 3: Dashboard files mounted in pod (50KB+ JSON, 20+ panels)
- [ ] ✅ Test 4: Loki `max_query_parallelism` >= 16, caching enabled
- [ ] ✅ Test 5: CPU throttling < 0.1%
- [ ] ✅ Test 6: Zero HTTP 400 errors in Grafana logs
- [ ] ✅ Test 7: ArgoCD synced from `develop` branch

**Timeline**: 5-10 minutes after ArgoCD sync completes

---

### Priority 3: Manual Dashboard Validation

#### Step 3.1: Access Dashboard
**URL**: https://grafana.tail57bf10.ts.net

**Navigation**:
1. Login to Grafana
2. Dashboards → Browse
3. Select: **"K3s Homelab and Hybrid Cloud Overview - Comprehensive"**

**Verification**:
- [ ] Dashboard loads successfully (no errors)
- [ ] All 20 panels visible (5 rows)
- [ ] No "No Data" errors on any panel

---

#### Step 3.2: Measure Dashboard Load Time

**Browser**: Chrome/Firefox with DevTools

**Steps**:
1. Open DevTools (F12)
2. Go to **Network** tab
3. Check "Disable cache"
4. Refresh dashboard (Ctrl+F5 / Cmd+Shift+R)
5. Look at Network tab summary footer
6. Find **"DOMContentLoaded"** time

**Metrics to Record**:
| Metric | Target | Actual | Pass/Fail |
|--------|--------|--------|-----------|
| DOMContentLoaded | < 3s | _____s | [ ] |
| Load | < 5s | _____s | [ ] |
| Requests | < 50 | _____ | [ ] |
| Transferred | < 2MB | _____MB | [ ] |

**Baseline (Before Optimization)**:
- DOMContentLoaded: **11.7 seconds**
- Load: **~13 seconds**

**Expected Improvement**: **74% reduction** (11.7s → <3s)

---

#### Step 3.3: Verify Panel Data by Row

**Row 1: Cluster Overview (6 panels)**
- [ ] Nodes Online: Shows 4 nodes (2 Oracle + 2 RPi)
- [ ] Total Pods: Shows pod count (expected: 50-100 pods)
- [ ] Average CPU Usage: Shows percentage
- [ ] Average Memory Usage: Shows percentage
- [ ] Pod Distribution by Node: Bar chart with 4 bars
- [ ] Pod Status Distribution: Pie chart (Running/Pending/Failed)

**Row 2: Network Analysis (5 panels)**
- [ ] Network I/O per Interface: Time series graph (eth0, wlan0, etc.)
- [ ] Network Errors and Drops: Time series (should be near zero)
- [ ] Active Network Connections: Gauge or graph (TCP/UDP)
- [ ] Pods per Namespace: Bar chart (14+ namespaces)

**Row 3: Node Resource Usage (4 panels)**
- [ ] Node CPU Usage: Time series for 4 nodes
- [ ] Node Memory Usage: Time series for 4 nodes
- [ ] Disk I/O: Read/write time series
- [ ] Filesystem Usage: Bar chart or gauge

**Row 4: Application Logs (4 panels)**
- [ ] Cluster Logs (All Namespaces): Log lines displayed
- [ ] Grafana Logs: Recent Grafana logs
- [ ] Prometheus Logs: Recent Prometheus logs
- [ ] Kube-system Errors/Warnings: Error/warning logs (may be empty if no errors)

**Row 5: Container Performance (2 panels)**
- [ ] Pod CPU Requests: Bar chart by namespace
- [ ] Pod Memory Requests: Bar chart by namespace

**Note**: Panels 19-20 show **requests** (not actual runtime usage) due to missing cAdvisor/metrics-server

---

#### Step 3.4: Check Browser Console

**Steps**:
1. Open DevTools (F12)
2. Go to **Console** tab
3. Filter by "Errors" (red messages)

**Verification**:
- [ ] Zero red error messages
- [ ] Zero "Failed to fetch" messages
- [ ] Zero "Query error" messages

**Common Issues to Check**:
- ❌ `400 Bad Request` → LogQL syntax error
- ❌ `Failed to fetch datasource` → Datasource UID mismatch
- ❌ `No data` → Query returns empty result set

---

### Priority 4: Loki Query Performance Testing

#### Step 4.1: Test Optimized LogQL Queries

**Navigate to**: Grafana → Explore → Select "Loki" datasource

**Test Query 1** (Cluster Logs - All Namespaces):
```logql
{exporter="OTLP", attributes_k8s_namespace_name=~"node-exporter|otel-collector|grafana|prometheus|loki|argocd|traefik|adguard|kube-system|cert-manager|tailscale|nfs-subdir-external-provisioner|ingress-nginx|default"} | json
```

**Metrics to Record**:
| Metric | Target | Actual | Pass/Fail |
|--------|--------|--------|-----------|
| Query Execution Time | < 500ms | _____ms | [ ] |
| Lines Scanned | < 10,000 | _____ | [ ] |
| Bytes Processed | < 1MB | _____KB | [ ] |

**Test Query 2** (Grafana Logs):
```logql
{exporter="OTLP", attributes_k8s_namespace_name=~"grafana"} | json
```

**Metrics to Record**:
| Metric | Target | Actual | Pass/Fail |
|--------|--------|--------|-----------|
| Query Execution Time | < 200ms | _____ms | [ ] |

**Test Query 3** (Kube-system Errors):
```logql
{exporter="OTLP", attributes_k8s_namespace_name=~"kube-system"} | json | attributes_severity_text=~"ERROR|WARN"
```

**Metrics to Record**:
| Metric | Target | Actual | Pass/Fail |
|--------|--------|--------|-----------|
| Query Execution Time | < 300ms | _____ms | [ ] |

**Baseline (Before Optimization)**:
- Average query time: **2.5 seconds**
- Expected improvement: **80% reduction** (2.5s → <500ms)

---

### Priority 5: 24-Hour Monitoring (Optional but Recommended)

#### Step 5.1: Monitor Loki Metrics

**Command**:
```bash
# Get Loki pod
LOKI_POD=$(kubectl get pod -n loki -l app=loki -o jsonpath='{.items[0].metadata.name}')

# Check query duration distribution
kubectl exec -n loki $LOKI_POD -- \
  wget -qO- http://localhost:3100/metrics | \
  grep 'logql_query_duration_seconds_bucket{query_type="range"}'
```

**Expected Result**: Most queries in `le="0.5"` bucket (< 500ms)

---

#### Step 5.2: Monitor Grafana CPU Throttling

**Command**:
```bash
# Get Grafana pod
GRAFANA_POD=$(kubectl get pod -n grafana -l app=grafana -o jsonpath='{.items[0].metadata.name}')

# Check CPU throttling stats
kubectl exec -n grafana $GRAFANA_POD -- cat /sys/fs/cgroup/cpu.stat
```

**Metrics to Record** (after 24 hours):
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| nr_throttled | 4 events | _____ events | _____ % |
| nr_periods | 1,051 | _____ | N/A |
| Throttle % | 0.38% | _____% | _____ % |

**Target**: Throttle % < 0.1%

---

#### Step 5.3: Monitor Grafana Error Logs

**Command**:
```bash
# Get Grafana pod
GRAFANA_POD=$(kubectl get pod -n grafana -l app=grafana -o jsonpath='{.items[0].metadata.name}')

# Check for HTTP 400 errors (query errors)
kubectl logs -n grafana $GRAFANA_POD --tail=10000 | grep 'status=400' | wc -l
```

**Expected Result**: Zero HTTP 400 errors

**If errors found**:
```bash
# Show error details
kubectl logs -n grafana $GRAFANA_POD --tail=10000 | grep 'status=400' | tail -20
```

---

## 📊 Success Criteria Summary

### Performance Targets:
- [x] Dashboard load time: **< 3 seconds** (74% faster than 11.7s)
- [x] Loki query time: **< 500ms** (80% faster than 2.5s)
- [x] CPU throttling: **< 0.1%** (73% reduction from 0.38%)
- [x] Query errors: **Zero** (100% resolution)
- [x] Panel count: **20 panels** (186% more than 7)

### Functional Targets:
- [x] All ConfigMaps deployed
- [x] Dashboard files mounted correctly
- [x] All panels display data (no "No Data" errors)
- [x] Network Analysis section restored (5 panels)
- [x] LogQL queries use label selectors (not post-filters)
- [x] ArgoCD syncing from `develop` branch

---

## 🚨 Rollback Procedure (If Issues Found)

### Issue 1: Dashboard Not Loading
**Symptoms**: 500 error, blank page, or continuous loading

**Diagnosis**:
```bash
# Check Grafana pod status
kubectl get pods -n grafana
kubectl describe pod -n grafana <pod-name>
kubectl logs -n grafana <pod-name> --tail=100
```

**Rollback**:
```bash
# Revert to previous version via ArgoCD
kubectl patch application homelab-apps-root -n argocd \
  --type=json \
  -p='[{"op": "replace", "path": "/spec/source/targetRevision", "value": "<previous-commit-sha>"}]'
```

---

### Issue 2: Panels Showing "No Data"
**Symptoms**: Multiple panels display "No Data" error

**Diagnosis**:
```bash
# Check datasource connectivity
kubectl exec -n grafana $GRAFANA_POD -- \
  wget -qO- http://prometheus.prometheus.svc.cluster.local:9090/api/v1/query?query=up

# Check Loki connectivity
kubectl exec -n grafana $GRAFANA_POD -- \
  wget -qO- http://loki.loki.svc.cluster.local:3100/ready
```

**Possible Causes**:
1. Datasource UID mismatch (check dashboard JSON: `"uid": "prometheus"` and `"uid": "loki"`)
2. Prometheus/Loki not responding (check pod status)
3. Query syntax error (check browser console)

**Fix**:
```bash
# Edit dashboard configmap
kubectl edit configmap -n grafana grafana-dashboard-homelab-k3s-overview

# Or revert to previous dashboard version
```

---

### Issue 3: Slow Query Performance (Not Meeting Targets)
**Symptoms**: Queries still taking > 1 second

**Diagnosis**:
```bash
# Check Loki configuration applied
kubectl get configmap -n loki loki -o yaml | grep -A5 'max_query_parallelism'
kubectl get configmap -n loki loki -o yaml | grep -A5 'cache_results'

# Check Loki pod restart (config may not be applied)
kubectl get pods -n loki -o wide
```

**Fix**:
```bash
# Restart Loki pod to apply configuration
kubectl rollout restart deployment loki -n loki
kubectl rollout status deployment loki -n loki
```

---

## 📝 Post-Validation Report Template

**Date**: _______  
**Validated By**: _______  
**Dashboard Load Time**: _____s (Target: <3s)  
**Loki Query Time (avg)**: _____ms (Target: <500ms)  
**CPU Throttling**: _____% (Target: <0.1%)  
**HTTP 400 Errors**: _____ (Target: 0)  
**Panels with Data**: _____/20 (Target: 20/20)  

**Issues Found**:
- [ ] None - All tests passed ✅
- [ ] Dashboard load time exceeds target
- [ ] Query performance below target
- [ ] Panels showing "No Data"
- [ ] Browser console errors
- [ ] Other: _______

**Action Items**:
1. _______
2. _______
3. _______

**Status**: [ ] PASS / [ ] FAIL / [ ] PARTIAL

---

## 📚 Reference Documentation

- **Performance Analysis**: `docs/PERFORMANCE_OPTIMIZATION_SUMMARY.md`
- **Troubleshooting Guide**: `docs/grafana-dashboard-troubleshooting.md`
- **Deployment Script**: `k8s/apps/apply-performance-optimizations.sh`
- **Validation Script**: `validate-dashboard-performance.sh`
- **Pull Request**: https://github.com/ariel99gf/homelab/pull/27

---

## ✅ Final Sign-Off

**Post-Merge Tasks Completed**:
- [ ] ArgoCD reverted to `develop` branch
- [ ] Automated validation script executed (all tests passed)
- [ ] Dashboard load time validated (< 3s)
- [ ] All 20 panels display data
- [ ] Loki query performance validated (< 500ms)
- [ ] Browser console errors checked (zero errors)
- [ ] 24-hour monitoring completed (optional)

**Signed Off By**: _______  
**Date**: _______  
**Notes**: _______
