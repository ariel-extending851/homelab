# Promtail (edge log shipper)

> **Status:** Active (introduced 2026-05-29, replaces Alloy edge from PR #114)
> **Doc:** [`../../../docs/architecture/observability-alloy-ebpf.md`](../../../docs/architecture/observability-alloy-ebpf.md) (see § Edge tier revision)
> **Owner:** @ariel-extending851

Lightweight log shipper for the Raspberry Pi edge tier. Tails container logs
from the standard k8s on-disk layout and pushes to Grafana Cloud Loki.

## Why Promtail (and not Alloy edge from PR #114)

PR #114 deployed Grafana Alloy as a native systemd service on both Pis via
`ansible/roles/alloy/`. After real-world validation, Alloy edge competed for
two resources Jellyfin transcoding also needs on rasp-pi-04:

1. **Apiserver chatter.** Alloy's `discovery.kubernetes` component polls the
   k3s apiserver to maintain pod targets. On rasp-pi-04 the apiserver IS the
   k3s-server process — so Alloy's discovery loop competed for CPU with k3s
   itself, which competed for I/O with Jellyfin reading transcoded chunks
   off the same disk.
2. **eBPF / Beyla overhead.** Even with Beyla "optional", the binary footprint
   plus the WAL writes added measurable I/O pressure.

The symptom was streaming lag while Alloy was active. Removing Alloy restored
smooth playback; the architecture needed an alternative for edge log shipping
that doesn't touch the apiserver and doesn't share Beyla's hot-path overhead.

Promtail (the original Grafana log shipper, predates Alloy in this codebase)
fits the constraint: file-based discovery via `static_configs` + `__path__`
glob, no apiserver calls, ~30 MB RSS, inotify-driven delta reads. The cloud
tier still runs Alloy + Beyla in `k8s/apps/alloy/` when AWS Full is active —
this PR does not touch that path.

## Architecture

```text
   rasp-pi-03 (Pi 3, 1 GB)              rasp-pi-04 (Pi 4, 8 GB)
   ───────────────────────              ───────────────────────
   /var/log/pods/.../X.log ─┐           /var/log/pods/.../X.log ─┐
                            │                                    │
            ┌───────────────┴────┐           ┌───────────────────┴───┐
            │ Promtail DaemonSet │           │ Promtail DaemonSet     │
            │ (~30 MB RSS)       │           │ (~30 MB RSS)           │
            │ inotify tail       │           │ inotify tail           │
            │ file-based only    │           │ file-based only        │
            │ NO apiserver calls │           │ NO apiserver calls     │
            └─────────┬──────────┘           └──────────┬─────────────┘
                      │                                 │
                      └───────────► Grafana Cloud Loki ◄┘
                                    (HTTPS, basic auth)
                                    external_labels:
                                      tier=edge
                                      cluster=homelab-pi
```

## Resource budget

| | Pi-03 (1 GB) | Pi-04 (8 GB) |
|---|---|---|
| Free + cache (baseline) | ~270 MB | ~4.1 GB |
| Promtail RSS request | 30 MiB | 30 MiB |
| Promtail RSS limit | 80 MiB | 80 MiB |
| Headroom after | ~190 MB | ~4.0 GB |

Pi-03 budget is intentionally tight — if Promtail OOMs there, the limit
needs revisiting before adding any more daemons to that node.

## Bootstrap (encrypted secret)

Promtail will not start without `secret.yaml` listed in `kustomization.yaml`.
Bootstrap workflow (one-time per cluster):

```bash
# 1. Render the example into /tmp (never commit unencrypted).
cp k8s/apps/promtail/secret.yaml.example /tmp/promtail-secret.yaml

# 2. Replace placeholders with the real Grafana Cloud Loki creds.
#    GRAFANA_CLOUD_LOKI_URL: from Grafana Cloud → My Account → Loki
#    GRAFANA_CLOUD_USER:     the numeric instance ID (NOT the email)
#    GRAFANA_CLOUD_TOKEN:    a glc_eyJ... token with Loki push scope
vim /tmp/promtail-secret.yaml

# 3. Encrypt in place via SOPS (recipient from .sops.yaml).
sops -e /tmp/promtail-secret.yaml > k8s/apps/promtail/secret.yaml
shred -u /tmp/promtail-secret.yaml

# 4. Verify the envelope decrypts.
sops -d k8s/apps/promtail/secret.yaml | head -5

# 5. Wire it into kustomize and commit.
#    Edit k8s/apps/promtail/kustomization.yaml — append `- secret.yaml`
#    under resources. Commit + open PR.
```

## Verification (post-deploy)

```bash
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml

# 1. ArgoCD picked up the new app.
kubectl -n argocd get app homelab-apps-root -o jsonpath='{.status.sync.status}'
# expect: Synced

# 2. Two pods (one per Pi), both Ready.
kubectl -n promtail get pod -o wide
# expect: 2 pods, one on rasp-pi-03 and one on rasp-pi-04, both 1/1 Ready

# 3. Footprint within budget.
kubectl -n promtail top pod
# expect: ~25-40 MiB RSS, single-digit milli-CPU

# 4. Logs reaching Grafana Cloud (browser).
# Go to Grafana Cloud → Explore → Loki, query:
#   {tier="edge", namespace="media"} |~ "."
# Expect: live tail of jellyfin / radarr / sonarr / etc.

# 5. No Jellyfin regression. Stream a 1080p title for 5 minutes. Watch
#    the network graph in qBittorrent and Jellyfin's transcoding logs.
#    Expect: zero new transcoding-stall events vs. baseline.

# 6. k3s-server CPU unchanged.
ssh ubuntu@192.168.8.11 'top -bn1 -p $(pidof k3s-server) | tail -3'
# Expect: %CPU within ±5 of the pre-deploy baseline (~33 %).
```

## When AWS Full comes back

Nothing in this directory needs to change. The nodeAffinity rule in
`daemonset.yaml` excludes nodes labelled `homelab.io/tier=cloud`, so when
the EC2 worker rejoins, Promtail will not schedule there — Alloy
(`k8s/apps/alloy/`) handles the cloud tier with its full eBPF + S3 stack.

If you ever want to retire Promtail entirely and run Alloy on the edge
again, the historical install lives in `ansible/roles/alloy/` — it is
marked legacy but the manifests remain for reference.
