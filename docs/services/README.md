# Services

> **Status:** Stub
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Index of every application deployed to the k3s cluster. Each row links to the canonical service doc; manifests are in [`k8s/apps/`](../../k8s/apps/) and synced via ArgoCD.

The table below is auto-generated from `k8s/apps/<app>/` by `bin/generate_service_catalog.py`. Run `make generate-catalog` after adding or removing an app; a pre-commit hook fails the build if the file drifts.

<!-- catalog:start -->
| App | Doc | Namespace | Ingress |
|---|---|---|---|
| AdGuard Home | [adguard.md](adguard.md) | `adguard` | <https://adguard.tail57bf10.ts.net> |
| blackbox | [monitoring-stack.md](monitoring-stack.md#blackbox) | `blackbox` | — |
| cilium | — | `—` | — |
| falco | — | `falco` | — |
| GoLink | [golink.md](golink.md) | `golink` | <https://golink.tail57bf10.ts.net> |
| Grafana | [grafana.md](grafana.md) | `grafana` | <https://grafana.tail57bf10.ts.net> |
| kube-state-metrics | [monitoring-stack.md](monitoring-stack.md#kube-state-metrics) | `kube-state-metrics` | — |
| Loki | [loki.md](loki.md) | `loki` | <https://loki.tail57bf10.ts.net> |
| node-exporter | [monitoring-stack.md](monitoring-stack.md#node-exporter) | `node-exporter` | — |
| otel-collector | [monitoring-stack.md](monitoring-stack.md#otel-collector) | `otel-collector` | — |
| prometheus | [monitoring-stack.md](monitoring-stack.md#prometheus) | `prometheus` | <https://prometheus.tail57bf10.ts.net> |
| Velero — Cluster Backup & Disaster Recovery | [velero.md](velero.md) | `velero` | — |
<!-- catalog:end -->

System-only components not deployed under `k8s/apps/` (e.g. Tailscale Operator) are documented separately:

- [Tailscale Operator](tailscale-operator.md) — installed as part of the cluster bootstrap, not a Kustomize app.
