# Runbook: Grafana Dashboards Broken

| Field | Value |
|:--- |:--- |
| **Severity** | 🟢 Info (cosmetic — metrics still flowing) |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-01-23 |
| **Owner** | @ariel-extending851 |

---

## Symptoms

- Panels showing **HTTP 400** errors or "No data"
- Dashboard load times in the seconds (target: <3 s)
- CPU throttling alerts on the Grafana pod

## Root Causes (most common, in order)

| # | Cause | Fix |
|---|---|---|
| 1 | LogQL query has the namespace filter **after** the pipe (`{} | json` style) | Move namespace into the label selector — see [Optimization](#query-optimization) |
| 2 | Default time range is wide (e.g., `now-6h`) | Reduce default to `now-1h` |
| 3 | Empty regex / malformed filter (`{label=~""}` or `|= ""`) | Use a non-empty matcher |
| 4 | Datasource UID mismatch (Prometheus query against Loki, or vice versa) | Edit panel → set correct datasource |
| 5 | Missing `$__from` / `$__to` variables in custom dashboard | Use Grafana built-ins or `now-1h` |

## Diagnosis

### 1. Check Grafana for HTTP 400 errors

```bash
kubectl logs -n grafana deploy/grafana --tail=200 | grep 'status=400'
```

Each line includes the panel UID and dashboard URL. Open in browser → Inspector → Query → see the failing query string.

### 2. Check Loki query latency

```bash
kubectl exec -n loki deploy/loki -- \
  wget -qO- localhost:3100/metrics | grep logql_query_duration_seconds_sum
```

P99 should be **< 500 ms**. If sustained above 2 s, queries are scanning too much data — fix with optimization below.

### 3. Check Grafana CPU throttling

```bash
kubectl exec -n grafana deploy/grafana -- \
  cat /sys/fs/cgroup/cpu.stat | grep nr_throttled
```

If `nr_throttled` is increasing, bump CPU limit in `k8s/apps/grafana/deployment.yaml` (current: 1000m).

## Resolution

### Query Optimization (the big win)

Move label filters into the **label selector** (before the `|` pipe), not after `| json` parsing. Loki filters by label selector before fetching chunks; pipe filters happen after.

**Bad** (slow, scans all logs):
```logql
{exporter="OTLP"} | json | attributes_k8s_namespace_name=~"node-exporter|kube-state" | line_format "{{.body}}"
```

**Good** (fast, ~10× less data scanned):
```logql
{exporter="OTLP", attributes_k8s_namespace_name=~"node-exporter|kube-state"} | json | line_format "{{.body}}"
```

### Reduce default time range

```json
{
  "time": {
    "from": "now-1h",
    "to": "now"
  }
}
```

A 6 h → 1 h reduction at 30-second resolution drops the data points from ~720 to ~120 per series.

### Use the provisioned dashboards (preferred)

Dashboards live in [`k8s/apps/grafana/dashboards/`](../../k8s/apps/grafana/dashboards/) committed as JSON, applied via the `grafana-dashboards` ConfigMap. To get the optimized dashboards:

```bash
# ArgoCD will sync within ~3 min, or force it:
kubectl rollout restart deployment grafana -n grafana
```

### Manual fix (one panel at a time)

1. Open dashboard → Settings (gear) → JSON Model
2. Locate the failing panel by UID (from the 400 log line)
3. Apply the appropriate fix from the table above
4. Save → confirm via `/api/ds/query` shows 200 in Grafana logs

## Verification

```bash
# Should see no 400s after ~30s
kubectl logs -n grafana deploy/grafana --tail=100 | grep 'status=400' | wc -l
# expect: 0

# Loki latency back to normal
kubectl exec -n loki deploy/loki -- \
  wget -qO- localhost:3100/metrics \
  | awk '/logql_query_duration_seconds{quantile="0.99"}/ {print $2}'
# expect: < 0.5
```

Reload the dashboard in the browser and confirm panels render in under 3 seconds.

## Prevention

- Author dashboards with the [LogQL performance guide](https://grafana.com/docs/loki/latest/logql/performance/)
- Validate every new dashboard query in **Explore** before saving
- Pre-commit hook: lint dashboard JSON for known anti-patterns (`|= ""`, `=~""`, post-pipe label filters)

## Related

- [`../services/loki.md`](../services/loki.md) — Loki retention + ingestion limits
- [`../services/grafana.md`](../services/grafana.md) — Grafana setup and ProxyClass
- [`../services/monitoring-stack.md`](../services/monitoring-stack.md) — Prometheus + scrape detail
