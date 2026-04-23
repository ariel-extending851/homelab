# Tailnet Services

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Every `*.tail57bf10.ts.net` hostname currently served by the cluster, and what it points at. All accessible only from devices on the tailnet.

---

## Cluster Apps

| Hostname | Service | Doc |
|---|---|---|
| <https://adguard.tail57bf10.ts.net> | AdGuard Home (DNS UI) | [adguard.md](../services/adguard.md) |
| <https://golink.tail57bf10.ts.net> | GoLink (short-link redirector) | [golink.md](../services/golink.md) |
| <https://grafana.tail57bf10.ts.net> | Grafana (high-bandwidth ProxyClass) | [grafana.md](../services/grafana.md) |
| <https://***.tail57bf10.ts.net> | *** (media streaming) | [***.md](../services/***.md) |
| <https://loki.tail57bf10.ts.net> | Loki (`/ready` health endpoint) | [loki.md](../services/loki.md) |
| <https://prometheus.tail57bf10.ts.net> | Prometheus UI (`/targets`, debug) | [monitoring-stack.md](../services/monitoring-stack.md#prometheus) |
| <https://***.tail57bf10.ts.net> | *** (indexer manager) | [***.md](../services/***.md) |
| <https://***.tail57bf10.ts.net> | *** (Web UI; traffic via *** VPN) | [***.md](../services/***.md) |
| <https://***.tail57bf10.ts.net> | *** | [***.md](../services/***.md) |
| <https://searxng.tail57bf10.ts.net> | SearXNG (Tailscale sidecar pattern) | [searxng.md](../services/searxng.md) |
| <https://***.tail57bf10.ts.net> | *** | [***.md](../services/***.md) |

Cluster-internal services (no ingress): blackbox, ***, kube-state-metrics, node-exporter, OTEL Collector. They're scraped/used by other in-cluster apps only.

---

## Tailnet Devices (not Kubernetes ingresses)

These are nodes that joined the tailnet directly (not through the operator):

| Device | What it is |
|---|---|
| `k3s-server-1` | AWS EC2 t3.medium, control plane |
| `k3s-agent-2` | AWS EC2 t3.small, worker |
| `rasp-pi-03` | RPi 3, low-memory worker |
| `rasp-pi-04` | RPi 4, storage-heavy worker |
| `searxng` | SearXNG pod (joined via Tailscale sidecar — legacy pattern) |
| `golink` | GoLink pod (joined via embedded `tsnet` — own auth key) |
| `pc-tower` | Workstation (Fedora) |
| `opal-gateway` | Home router |

The Tailscale operator also creates one `ts-<ingress-name>` device per Ingress for the apps in the table above — those appear as ephemeral devices in the tailnet admin console.

---

## How Hostnames Get Created

| Hostname source | Mechanism |
|---|---|
| `<app>.tail57bf10.ts.net` for app ingresses | Tailscale Kubernetes operator picks the `host` field from the Ingress and creates a tailnet device with that name. See [`../services/tailscale-operator.md`](../services/tailscale-operator.md). |
| `searxng` | Per-pod Tailscale sidecar (`TS_HOSTNAME=searxng`). Legacy pattern. |
| `golink` | Embedded `tsnet` instance with `hostname: golink`. |

If you add a new app with a Tailscale Ingress, the operator picks up the `host` automatically — no manual tailnet config needed.

---

## DNS / Reachability Notes

- **MagicDNS** must be enabled in the tailnet (<https://login.tailscale.com/admin/dns>)
- Without MagicDNS, you must use the full `*.tail57bf10.ts.net` form (the tailnet ID `tail57bf10` is in [`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml))
- TLS certs are managed automatically by Tailscale (Let's Encrypt under the hood)
- ACLs in the Tailscale console can restrict which devices reach which hostnames (this repo doesn't manage Tailscale ACLs)

---

## Adding a New Hostname

1. Add an `Ingress` manifest under `k8s/apps/<newapp>/ingress.yaml`:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: newapp-ingress
     namespace: newapp
   spec:
     ingressClassName: tailscale
     rules:
       - host: newapp.tail57bf10.ts.net
         http:
           paths:
             - path: /
               pathType: Prefix
               backend:
                 service:
                   name: newapp
                   port:
                     number: 80
     tls:
       - hosts: [newapp.tail57bf10.ts.net]
   ```
2. Commit + push; ArgoCD applies; the operator creates the proxy + tailnet device automatically (~30 s).
3. Update this page with the new entry.

---

## Related

- **Tailscale operator architecture:** [`../services/tailscale-operator.md`](../services/tailscale-operator.md)
- **Networking deep-dive:** [`../architecture/networking.md`](../architecture/networking.md)
- **Recovery when tailnet auth fails:** [`../runbooks/tailscale-logged-out.md`](../runbooks/tailscale-logged-out.md)
