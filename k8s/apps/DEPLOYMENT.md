# Modular GitOps Deployment Guide

## Overview
This directory contains the refactored, modular Kubernetes manifests following GitOps best practices with **Tailscale Zero Trust** sidecar pattern.

## Architecture Changes

### Migrated Services
| Service | Old Location | New Location | Tailscale Sidecar |
|---------|--------------|--------------|-------------------|
| Grafana | 01-monitoring-core.yaml | apps/grafana/ | ✅ Yes |
| Prometheus | 01-monitoring-core.yaml | apps/prometheus/ | ✅ Yes |
| OTEL Collector | 02-otel-agent.yaml | apps/otel-collector/ | ❌ No (DaemonSet) |
| Kube State Metrics | 03-kube-state-metrics.yaml | apps/kube-state-metrics/ | ❌ No (Metrics Only) |
| Loki | 04-loki-server.yaml | apps/loki/ | ✅ Yes |
| Blackbox Exporter | 06-blackbox.yaml | apps/blackbox/ | ❌ No (Metrics Only) |
| AdGuard Home | adguard.yaml | apps/adguard/ | ✅ Yes (Admin UI) |
| Node Exporter | 05-node-exporter.yaml | apps/node-exporter/ | ❌ No (DaemonSet) |

## Prerequisites

### 1. Generate Tailscale Auth Keys
Visit: https://login.tailscale.com/admin/settings/keys

**Recommended Settings:**
- **Reusable:** Yes (for pod restarts)
- **Ephemeral:** No (maintain persistent identity)
- **Pre-approved:** Yes
- **Tags:** `tag:k8s`, `tag:<service-name>`

### 2. Create Secrets
```bash
# Grafana
kubectl create secret generic tailscale-auth \
  --from-literal=authkey=tskey-auth-XXXXXXXXXXXX \
  -n grafana

# Prometheus
kubectl create secret generic tailscale-auth \
  --from-literal=authkey=tskey-auth-XXXXXXXXXXXX \
  -n prometheus

# Loki
kubectl create secret generic tailscale-auth \
  --from-literal=authkey=tskey-auth-XXXXXXXXXXXX \
  -n loki

# AdGuard
kubectl create secret generic tailscale-auth \
  --from-literal=authkey=tskey-auth-XXXXXXXXXXXX \
  -n adguard
```

**Note:** You can use the same auth key for all services if you enable "Reusable" mode.

## Deployment Order

Deploy services in dependency order to ensure proper startup:

### Step 1: Foundation Services (No Dependencies)
```bash
kubectl apply -k k8s/apps/kube-state-metrics/
kubectl apply -k k8s/apps/node-exporter/
kubectl apply -k k8s/apps/blackbox/
```

### Step 2: Log Aggregation (Depends on Nothing)
```bash
kubectl apply -k k8s/apps/loki/
```

### Step 3: OTEL Collector (Sends logs to Loki)
```bash
# Wait for Loki to be ready
kubectl wait --for=condition=ready pod -l app=loki -n loki --timeout=300s

kubectl apply -k k8s/apps/otel-collector/
```

### Step 4: Prometheus (Scrapes all metrics exporters)
```bash
# Wait for kube-state-metrics and node-exporter
kubectl wait --for=condition=ready pod -l app=kube-state-metrics -n kube-state-metrics --timeout=120s
kubectl wait --for=condition=ready pod -l app=node-exporter -n node-exporter --timeout=120s

kubectl apply -k k8s/apps/prometheus/
```

### Step 5: Grafana (Connects to Prometheus + Loki)
```bash
# Wait for Prometheus to be ready
kubectl wait --for=condition=ready pod -l app=prometheus -n prometheus --timeout=300s

kubectl apply -k k8s/apps/grafana/
```

### Step 6: AdGuard (Independent)
```bash
kubectl apply -k k8s/apps/adguard/
```

## Verification

### Check Pod Status
```bash
# All monitoring services
kubectl get pods -A | grep -E 'grafana|prometheus|loki|otel|kube-state|node-exporter|blackbox'

# Check Tailscale sidecars
kubectl get pods -n grafana -o jsonpath='{.items[*].spec.containers[*].name}' | grep tailscale
kubectl get pods -n prometheus -o jsonpath='{.items[*].spec.containers[*].name}' | grep tailscale
kubectl get pods -n loki -o jsonpath='{.items[*].spec.containers[*].name}' | grep tailscale
kubectl get pods -n adguard -o jsonpath='{.items[*].spec.containers[*].name}' | grep tailscale
```

### Check Tailscale Registration
```bash
# From your machine with Tailscale CLI
tailscale status

# You should see these nodes:
# - grafana
# - prometheus
# - loki
# - adguard
```

### Access Services via HTTPS
Once Tailscale sidecars are connected:

```bash
# Grafana (replace 'your-tailnet' with your actual Tailscale network name)
https://grafana.your-tailnet.ts.net

# Prometheus
https://prometheus.your-tailnet.ts.net

# Loki (for querying logs)
https://loki.your-tailnet.ts.net

# AdGuard Admin Panel
https://adguard.your-tailnet.ts.net
```

**Note:** Tailscale automatically provisions Let's Encrypt HTTPS certificates for all served applications.

## Configuration Updates

### Update Grafana Datasources
Since namespaces have changed, update datasource URLs in Grafana:

**Prometheus Datasource:**
```yaml
url: http://prometheus.prometheus.svc.cluster.local:9090
```

**Loki Datasource:**
```yaml
url: http://loki.loki.svc.cluster.local:3100
```

### Update Prometheus Scrape Configs
The Prometheus ConfigMap already includes updated service discovery for:
- `kube-state-metrics.kube-state-metrics.svc.cluster.local:8080`
- `blackbox-exporter.blackbox.svc.cluster.local:9115`
- `otel-collector` pods (via Kubernetes SD)
- `node-exporter` endpoints (via Kubernetes SD)

## Troubleshooting

### Tailscale Sidecar Not Connecting
```bash
# Check logs
kubectl logs -n grafana deployment/grafana -c tailscale

# Common issues:
# 1. Invalid auth key -> Check secret
# 2. TPM errors -> Ensure TS_KUBE_SECRET="" is set
# 3. State dir not persisted -> Check PVC mount
```

### Prometheus Not Scraping Targets
```bash
# Check Prometheus targets page
https://prometheus.your-tailnet.ts.net/targets

# Verify service discovery
kubectl get endpoints -n kube-state-metrics
kubectl get endpoints -n node-exporter
```

### AdGuard DNS Not Working
```bash
# Check if pod is using hostNetwork
kubectl get pod -n adguard -o jsonpath='{.items[*].spec.hostNetwork}'
# Should return: true

# Verify port 53 is bound on the host
kubectl exec -n adguard deployment/adguardhome -c adguardhome -- netstat -tuln | grep :53
```

### OTEL Collector Logs Not Appearing in Loki
```bash
# Check OTEL Collector logs
kubectl logs -n otel-collector daemonset/otel-collector

# Verify Loki is receiving data
kubectl logs -n loki deployment/loki -c loki | grep "POST /loki/api/v1/push"
```

## Hardware-Aware Scheduling

### Current Node Assignments
| Service | Node | Reason |
|---------|------|--------|
| Grafana | k3s-node-0 (Oracle) | Memory-intensive |
| Prometheus | k3s-node-0 (Oracle) | Memory-intensive + TSDB storage |
| Loki | k3s-node-1 (Oracle) | I/O intensive (log storage) |
| AdGuard | rasp-pi-03 | Needs hostNetwork + local PV |
| Blackbox | Control Plane | Lightweight, saves Pi resources |
| OTEL Collector | All nodes | DaemonSet (host metrics) |
| Node Exporter | All nodes | DaemonSet (host metrics) |
| Kube State Metrics | Any node | Lightweight |

### Modify Node Affinity
To change scheduling, edit the `nodeSelector` in each `deployment.yaml`:

```yaml
nodeSelector:
  kubernetes.io/hostname: <your-node-name>
```

## Cleanup

### Remove Old Monolithic Manifests
**⚠️ Only after verifying the new setup works!**

```bash
# Backup first
cp k8s/01-monitoring-core.yaml k8s/backup/
cp k8s/02-otel-agent.yaml k8s/backup/
cp k8s/03-kube-state-metrics.yaml k8s/backup/
cp k8s/04-loki-server.yaml k8s/backup/
cp k8s/05-node-exporter.yaml k8s/backup/
cp k8s/06-blackbox.yaml k8s/backup/
cp k8s/adguard.yaml k8s/backup/

# Then delete
rm k8s/01-monitoring-core.yaml
rm k8s/02-otel-agent.yaml
rm k8s/03-kube-state-metrics.yaml
rm k8s/04-loki-server.yaml
rm k8s/05-node-exporter.yaml
rm k8s/06-blackbox.yaml
rm k8s/adguard.yaml
```

## Migration Rollback

If issues occur, rollback using:

```bash
# Delete new apps
kubectl delete -k k8s/apps/grafana/
kubectl delete -k k8s/apps/prometheus/
kubectl delete -k k8s/apps/loki/
kubectl delete -k k8s/apps/otel-collector/
kubectl delete -k k8s/apps/kube-state-metrics/
kubectl delete -k k8s/apps/blackbox/
kubectl delete -k k8s/apps/adguard/
kubectl delete -k k8s/apps/node-exporter/

# Restore old manifests
kubectl apply -f k8s/backup/01-monitoring-core.yaml
kubectl apply -f k8s/backup/02-otel-agent.yaml
kubectl apply -f k8s/backup/03-kube-state-metrics.yaml
kubectl apply -f k8s/backup/04-loki-server.yaml
kubectl apply -f k8s/backup/05-node-exporter.yaml
kubectl apply -f k8s/backup/06-blackbox.yaml
kubectl apply -f k8s/backup/adguard.yaml
```

## Next Steps

1. ✅ Deploy all services following the order above
2. ✅ Verify Tailscale connectivity (`tailscale status`)
3. ✅ Test HTTPS access to all web UIs
4. ✅ Update Grafana datasources
5. ✅ Verify Prometheus is scraping all targets
6. ✅ Confirm logs are flowing to Loki
7. ✅ Test AdGuard DNS resolution
8. ⏹️ Remove old monolithic manifests (after 48h of stability)
9. ⏹️ Document Tailscale hostnames in your team wiki

## Security Notes

- **Zero Trust:** All web UIs now require Tailscale authentication
- **No NodePorts:** Removed external ports (except AdGuard DNS:53 on hostNetwork)
- **State Persistence:** Tailscale state is stored in PVCs to prevent node identity changes
- **Read-Only Root:** All containers use read-only root filesystems where possible
- **Drop Capabilities:** All capabilities dropped except where required (AdGuard DNS)

## Support

For issues, check:
1. Pod logs: `kubectl logs -n <namespace> deployment/<name> -c <container>`
2. Events: `kubectl get events -n <namespace> --sort-by='.lastTimestamp'`
3. Describe pod: `kubectl describe pod -n <namespace> <pod-name>`
4. Tailscale status: `tailscale status` (from CLI) or `kubectl exec -it -n <namespace> deployment/<name> -c tailscale -- tailscale status`
