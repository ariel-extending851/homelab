# GoLink

> **Status:** Active · **Node:** any · **Namespace:** golink · **Ingress:** <https://golink.tail57bf10.ts.net>
> **Manifests:** [`k8s/apps/golink/`](../../k8s/apps/golink/) · **Last reviewed:** 2026-04-23

[GoLink](https://github.com/tailscale/golink) — Tailscale's open-source short-link redirector. Provides `go/<keyword>` redirects across the tailnet.

## Overview

## Architecture

- **Deployment:** single replica, no node affinity (lightweight Go binary)
- **Storage:** 1 Gi PVC for SQLite link database (`local-path-provisioner`)
- **Tailscale auth:** uses a Tailscale auth key from the `tailscale-auth-key` Secret to join the tailnet directly (`hostname: golink`)
- **Ingress:** Tailscale operator at `golink.tail57bf10.ts.net`

The pod itself runs an embedded `tsnet` instance, so it appears as a discrete tailnet node. This is why a separate auth key is needed per pod.

## Why Kubernetes (vs systemd)

The original design considered running this directly as a systemd service on a Pi. Decision: keep in Kubernetes for GitOps alignment.

| Pro | Con |
|---|---|
| Same deployment pattern as the rest of the stack | Slight overhead from container runtime |
| Manifests in version control / auditable | Slightly more complex networking |
| RBAC + resource limits | |
| Rolling updates with zero downtime | |
| Secret management via SOPS-encrypted Secret | |

The marginal resource savings of bare systemd don't outweigh the GitOps consistency.

## Setup: Tailscale Auth Key

GoLink joins the tailnet as its own node, so it needs its own auth key.

1. Generate at <https://login.tailscale.com/admin/settings/keys> with:
   - Reusable: **No** (one-time)
   - Ephemeral: **No** (persist across pod restarts)
   - Pre-approved: **Yes**
   - Tags: `tag:golink` (recommended for ACL targeting)
2. Set the secret (SOPS-encrypted in the repo):
   ```bash
   sops k8s/apps/golink/secret.yaml
   # set: stringData.authkey = "tskey-auth-XXXXXXXXXXXX-YYYYYYYYYYYYYYYYYYYY"
   ```
3. Commit + push; ArgoCD syncs.

## Resource Allocation

| Resource | Request | Limit |
|---|---|---|
| CPU | 50m | 200m |
| Memory | 64Mi | 128Mi |
| Storage | 1Gi (SQLite) | — |

Tuned for RPi 3 (which can host this pod when AWS isn't running).

## Security Hardening

- Runs as **UID 65532** (non-root)
- All Linux capabilities dropped
- Strict CPU/memory limits
- Liveness + readiness probes
- Dedicated ServiceAccount with minimal permissions

## Operations

### Add a link

### Backup the link DB

```bash
kubectl exec -n golink deploy/golink -- \
  cat /home/nonroot/links.db > golink-backup-$(date +%F).db
```

### Restart

```bash
kubectl rollout restart deployment golink -n golink
```

## Troubleshooting

### Pod `Pending` — PVC won't bind
`local-path-provisioner` should be running (k3s default). Check:
```bash
kubectl get sc
kubectl get pvc -n golink
```

### Pod OOMKilled
Memory limit (128Mi) is generous for the typical link table. If you have thousands of links, bump to 256Mi.

### "Invalid auth key"
The key may have been used (one-time) or expired. Generate a new one and update the secret.

### Pod runs but isn't reachable on tailnet
Check the embedded tsnet logs:
```bash
kubectl logs -n golink deploy/golink | grep -i tsnet
```
Confirm the auth key was accepted.

## Related

- **Networking model:** [`../architecture/networking.md`](../architecture/networking.md)
- **All ingress hostnames:** [`../reference/tailnet-services.md`](../reference/tailnet-services.md)
