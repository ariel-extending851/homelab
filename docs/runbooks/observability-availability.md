# Observability Stack — Single-Replica Trade-Off

Grafana, Loki, and Prometheus are deployed as **single-replica Deployments
backed by ReadWriteOnce PVCs**. This is intentional for the homelab cost
envelope, but it means the audit will continue to flag them as "critical
apps without PDBs". This document explains why we don't add PDBs and what
true HA would require.

## Why no PDBs on these three

A `PodDisruptionBudget` only meaningfully protects an app with ≥2 replicas:

| PDB on `replicas: 1` | Effect |
|---|---|
| `maxUnavailable: 1` | Allows the sole replica to be evicted — no protection. Lies in dashboards. |
| `maxUnavailable: 0` | Blocks every `kubectl drain`. Operationally hostile during routine maintenance. |
| `minAvailable: 1` | Same as `maxUnavailable: 0`. Blocks all voluntary disruption. |

For involuntary disruptions (node failure, spot interruption) PDBs do not
apply at all — the pod just dies and gets rescheduled. With ReadWriteOnce
PVCs that means downtime until the new pod attaches the volume.

The other observability apps (`otel-collector`, `node-exporter`,
`kube-state-metrics`, `blackbox`) **do** have PDBs because they run as
DaemonSets or have multiple replicas — there a `maxUnavailable: 1` PDB
correctly enforces "drain one node at a time".

## Real HA, when we want it

| App | Path to HA | Cost / complexity |
|---|---|---|
| Grafana | Switch SQLite to external Postgres (RDS or in-cluster CNPG); replicas ≥2 | RDS ~$15/mo, or CNPG operator install |
| Loki | Microservices mode + S3 backend (already have); ingester/distributor/querier separated | Significant Helm chart change; 5-10x manifest count |
| Prometheus | Either Thanos sidecar (long-term storage in S3, query federation) or two-replica deploy with separate PVCs and Grafana datasource fan-out | Thanos: ~1.5x infra cost + operational burden |

Pick when an actual incident shows the downtime window matters more than
the cost / operational simplicity we get today.

## How to plan for downtime during maintenance

Because there are no PDBs, `kubectl drain <node>` will just evict these
pods. Window is roughly:

- Grafana: ~30s (re-attach PVC + start)
- Loki: ~1-2 min (chunk index recovery)
- Prometheus: ~1-2 min (WAL replay)

Schedule node maintenance windows accordingly. Velero backups already
cover the data side — see `make test-velero-restore` (runs
`bin/tests/test_velero_restore_live.py`).
