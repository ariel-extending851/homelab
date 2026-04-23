# Grafana

> **Status:** Active · **Node:** any · **Namespace:** grafana · **Ingress:** <https://grafana.tail57bf10.ts.net>
> **Manifests:** [`k8s/apps/grafana/`](../../k8s/apps/grafana/) · **Last reviewed:** 2026-04-23

Metrics + log dashboarding. Reads from Prometheus and Loki (in-cluster). Uses the **`high-bandwidth`** Tailscale ProxyClass because dashboards stream a lot of data.

## Overview

Single-replica Grafana with persistent storage for dashboards. The admin password is in a SOPS-encrypted Secret. Datasources for Prometheus and Loki are pre-provisioned via ConfigMap so the UI shows them on first login.

## Architecture

| Component | Detail |
|---|---|
| Namespace | `grafana` |
| Storage | PVC for SQLite (dashboards, alerts, plugins) |
| Datasources | Prometheus (`http://prometheus.monitoring.svc:9090`), Loki (`http://loki.loki.svc:3100`) — provisioned via ConfigMap |
| Auth | Local admin only (anonymous viewer disabled). Credentials in `grafana-secret` |
| Ingress class | `tailscale` |
| Ingress proxy class | `high-bandwidth` (label on the Service) |

## Configuration

Admin password is in [`k8s/apps/grafana/secret.yaml`](../../k8s/apps/grafana/secret.yaml) (SOPS-encrypted). To rotate:

```bash
sops k8s/apps/grafana/secret.yaml      # update GF_SECURITY_ADMIN_PASSWORD
git add ... && git commit && git push  # ArgoCD applies; pod restarts on next sync
```

Or one-shot:
```bash
kubectl set env deployment/grafana -n grafana \
  GF_SECURITY_ADMIN_PASSWORD='<new-password>'
```

## Operations

### Access

```text
https://grafana.tail57bf10.ts.net
```

Default user: `admin`. Password from the secret.

### Reset admin password (locked out)

```bash
kubectl exec -n grafana deploy/grafana -- \
  grafana-cli admin reset-admin-password "<new-password>"
```

### Restart

```bash
kubectl rollout restart deployment grafana -n grafana
```

### Backup dashboards

```bash
# Export all dashboards via API
TOKEN=$(kubectl exec -n grafana deploy/grafana -- \
  grafana-cli api token-create --name backup --role Admin)
curl -H "Authorization: Bearer $TOKEN" \
  https://grafana.tail57bf10.ts.net/api/search?type=dash-db | jq
```

Or snapshot the PVC directory on the underlying node.

## Dashboards

Dashboards are committed to git as JSON under `k8s/apps/grafana/dashboards/` and provisioned via the `grafana-dashboards` ConfigMap. Add a new dashboard:

1. Build it in the UI (or import from grafana.com)
2. Dashboard settings → JSON Model → copy
3. Save as `k8s/apps/grafana/dashboards/<name>.json`
4. Update `grafana-dashboards-configmap.yaml` to include it
5. Commit + push; ArgoCD applies

## Troubleshooting

### Login loops to /login page

Cookie/session DB issue. Restart the pod; if it persists, the PVC is corrupted:
```bash
kubectl exec -n grafana deploy/grafana -- \
  sqlite3 /var/lib/grafana/grafana.db 'PRAGMA integrity_check;'
```

### Datasource shows "no data"

Confirm Prometheus / Loki Services are reachable:
```bash
kubectl exec -n grafana deploy/grafana -- \
  wget -qO- http://prometheus.monitoring:9090/-/healthy
kubectl exec -n grafana deploy/grafana -- \
  wget -qO- http://loki.loki:3100/ready
```

If ready but no data, check the dashboard's time range and that Prometheus is actually scraping the relevant targets (Status → Targets in Prometheus).

### Slow dashboard load

Confirm the ProxyClass is `high-bandwidth`:
```bash
kubectl get svc grafana -n grafana -o jsonpath='{.metadata.labels}'
# expect: tailscale.com/proxy-class=high-bandwidth
```

If absent, the Tailscale operator picks the `default` proxy class which has tighter resources.

## Related

- **Loki / log queries:** [`loki.md`](loki.md)
- **Prometheus / metrics:** [`monitoring-stack.md`](monitoring-stack.md)
- **Dashboard runbook:** [`../runbooks/grafana-dashboards.md`](../runbooks/grafana-dashboards.md)
- **ProxyClass detail:** [`../architecture/networking.md#proxy-classes`](../architecture/networking.md#proxy-classes)
