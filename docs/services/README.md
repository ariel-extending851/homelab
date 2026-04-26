# Services

> **Status:** Stub
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Index of every application deployed to the k3s cluster. Each row links to the canonical service doc; manifests are in [`k8s/apps/`](../../k8s/apps/) and synced via ArgoCD.

| App | Doc | Namespace | Node | Ingress |
|---|---|---|---|---|
| AdGuard Home | [adguard.md](adguard.md) | `adguard` | rasp-pi-03 | <https://adguard.tail57bf10.ts.net> |
| Blackbox Exporter | [monitoring-stack.md](monitoring-stack.md#blackbox) | `monitoring` | any | — |
| GoLink | [golink.md](golink.md) | `golink` | any | <https://golink.tail57bf10.ts.net> |
| Grafana | [grafana.md](grafana.md) | `grafana` | any | <https://grafana.tail57bf10.ts.net> |
| kube-state-metrics | [monitoring-stack.md](monitoring-stack.md#kube-state-metrics) | `monitoring` | any | — |
| Loki | [loki.md](loki.md) | `loki` | any | <https://loki.tail57bf10.ts.net> |
| node-exporter | [monitoring-stack.md](monitoring-stack.md#node-exporter) | `monitoring` | DaemonSet | — |
| OTEL Collector | [monitoring-stack.md](monitoring-stack.md#otel-collector) | `otel-collector` | any | — |
| Prometheus | [monitoring-stack.md](monitoring-stack.md#prometheus) | `monitoring` | any | <https://prometheus.tail57bf10.ts.net> |
| SearXNG | [searxng.md](searxng.md) | `media` | rasp-pi-03 | <https://searxng.tail57bf10.ts.net> |
| Tailscale Operator | [tailscale-operator.md](tailscale-operator.md) | `tailscale` | system | (controller) |

Sources verified against `ls k8s/apps/` and ingress hostnames from each app's `ingress.yaml`.
