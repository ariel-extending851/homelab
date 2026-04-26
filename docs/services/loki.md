# Loki

> **Status:** Active · **Node:** any · **Namespace:** loki · **Ingress:** <https://loki.tail57bf10.ts.net>
> **Manifests:** [`k8s/apps/loki/`](../../k8s/apps/loki/) · **Last reviewed:** 2026-04-23

Log aggregation backend for Grafana. Single-binary Loki running in `monolithic` mode (no microservices split — appropriate for homelab scale).

## Overview

Pods across the cluster ship logs to Loki via Promtail (running as a DaemonSet, deployed alongside the OTEL collector). Loki stores them on a PVC and serves LogQL queries to Grafana.

## Architecture

| Component | Detail |
|---|---|
| Namespace | `loki` |
| Mode | Single binary (monolithic) |
| Storage backend | Filesystem (local PVC) — no S3/object store |
| Retention | 7 days (configured in `loki-config` ConfigMap) |
| Ingester writes | `/data/loki/chunks` |
| Index | `/data/loki/index` |
| Auth | Disabled (cluster-internal access only; tailnet ingress restricted by ACL) |

## Configuration

The full Loki YAML lives in [`k8s/apps/loki/configmap.yaml`](../../k8s/apps/loki/configmap.yaml). Key knobs:

```yaml
limits_config:
  retention_period: 168h          # 7 days
  ingestion_rate_mb: 4            # per-tenant rate limit
  max_query_series: 5000

compactor:
  retention_enabled: true
  delete_request_store: filesystem
```

Promtail config lives with the otel-collector setup — it scrapes:
- All container logs in `/var/log/pods/*/*.log`
- Per-pod labels (namespace, app, container)

## Operations

### Access

Direct UI: `https://loki.tail57bf10.ts.net` (mostly for `/ready` health endpoint). For real querying, use Grafana's Explore tab with the Loki datasource.

### LogQL examples

```logql
# All logs from a namespace
{namespace="media"}

# Errors only across all namespaces
{} |~ "(?i)(error|fail|exception)"

# Logs from a specific pod
```

### Restart

```bash
kubectl rollout restart deployment loki -n loki
```

### Check ingestion rate

```bash
kubectl exec -n loki deploy/loki -- wget -qO- localhost:3100/metrics \
  | grep loki_distributor_bytes_received_total
```

### Free up disk

```bash
# View disk use
kubectl exec -n loki deploy/loki -- du -sh /data/loki/*

# Force compactor to run
kubectl exec -n loki deploy/loki -- wget -qO- -X POST localhost:3100/compactor/ring
```

## Troubleshooting

### Loki returns `429 Too Many Requests`

Ingestion rate exceeded. Check:
```bash
kubectl exec -n loki deploy/loki -- wget -qO- localhost:3100/metrics \
  | grep loki_request_duration_seconds_count
```

Mitigation: bump `limits_config.ingestion_rate_mb` in the ConfigMap, or reduce log volume (drop debug logs at source).

### Grafana shows "datasource error: timeout"

Loki may be running but unreachable. Check:
```bash
kubectl get pods -n loki -o wide
kubectl exec -n loki deploy/loki -- wget -qO- localhost:3100/ready
```

Network policy could be blocking — confirm `monitoring` namespace egress allows `loki.loki:3100`.

### PVC full

Retention is 7 days. If the PVC is full sooner, you have a high-volume noisy logger. Find the culprit:
```bash
kubectl exec -n loki deploy/loki -- du -sh /data/loki/chunks/* | sort -h | tail -5
```

Then squash the noisy logger (often reduce verbosity in app config).

## Related

- **Grafana / dashboards:** [`grafana.md`](grafana.md)
- **Logs flow / Promtail:** [`monitoring-stack.md#otel-collector`](monitoring-stack.md#otel-collector)
- **Querying patterns:** [`../troubleshooting/torrent-p2p.md`](../troubleshooting/torrent-p2p.md) has good LogQL examples
