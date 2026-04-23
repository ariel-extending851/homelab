# SearXNG

> **Status:** Active · **Node:** rasp-pi-03 · **Namespace:** searxng · **Ingress:** <https://searxng.tail57bf10.ts.net>
> **Manifests:** [`k8s/apps/searxng/`](../../k8s/apps/searxng/) · **Last reviewed:** 2026-04-23

[SearXNG](https://docs.searxng.org/) — privacy-respecting metasearch engine. Runs on rasp-pi-03 with a Tailscale sidecar for direct HTTPS access.

## Overview

SearXNG aggregates results from multiple search engines without tracking the user. Tuned for the rasp-pi-03's tight memory budget (~800 MB free). The pod has a Tailscale sidecar so it appears on the tailnet as `searxng.tail57bf10.ts.net` directly — no need for a separate Ingress proxy.

## Architecture

```text
[User] -- HTTPS --> [Tailnet] -- HTTPS:443 --> [Tailscale sidecar] -- HTTP:8080 --> [SearXNG]
                                                     (same pod on rasp-pi-03)
```

| Component | Detail |
|---|---|
| Namespace | `searxng` |
| Pod | 2-container: `searxng` + `tailscale` sidecar |
| PVC | `searxng-tailscale-state` (persists tailnet identity across pod restarts) |
| ConfigMap | SearXNG `settings.yml` |
| Secrets | `searxng-secret` (app secret key), `searxng-tailscale-auth` (auth key) |
| Image (search) | `searxng/searxng:latest` (multi-arch incl. ARM64) |
| Image (sidecar) | `tailscale/tailscale:latest` (multi-arch) |

> **Sidecar pattern (legacy).** This is one of two apps still using the per-pod Tailscale sidecar pattern. New apps should use the cluster-wide Tailscale operator instead — see [`tailscale-operator.md`](tailscale-operator.md). SearXNG is grandfathered because the migration risk on a 1 GB Pi outweighs the upside.

## Resource Limits (RPi 3 budget)

| Container | CPU req / lim | Mem req / lim |
|---|---|---|
| searxng | 100m / 500m | 150Mi / 400Mi |
| tailscale | 50m / 200m | 64Mi / 128Mi |
| **Total** | **150m / 700m** | **214Mi / 528Mi** |

Total fits comfortably in the rasp-pi-03 1 GB RAM with kernel + kubelet overhead.

## Setup

### 1. Tailscale auth key

At <https://login.tailscale.com/admin/settings/keys> generate with:
- **Reusable:** Yes (required because pod restarts re-auth)
- **Ephemeral:** No (preserve identity)
- **Pre-approved:** Yes
- **Tags:** `tag:k8s`, `tag:searxng`
- **Expiration:** 90 days (or longer per your policy)

### 2. Apply secrets

Encrypted in repo via SOPS (preferred):
```bash
sops k8s/apps/searxng/secret.yaml      # set authkey + secret-key
git add k8s/apps/searxng/secret.yaml && git commit && git push
```

Or one-shot:
```bash
kubectl create secret generic searxng-tailscale-auth -n searxng \
  --from-literal=authkey=tskey-auth-XXXXXXXX
kubectl create secret generic searxng-secret -n searxng \
  --from-literal=secret-key=$(openssl rand -hex 32)
```

### 3. Apply manifests (or wait for ArgoCD)

```bash
kubectl apply -k k8s/apps/searxng/
```

### 4. Verify

```bash
kubectl get pods -n searxng -o wide       # 2/2 Running on rasp-pi-03
kubectl get pvc -n searxng                # Bound
kubectl logs -n searxng -l app=searxng -c searxng
kubectl logs -n searxng -l app=searxng -c tailscale
```

Tailnet check: <https://login.tailscale.com/admin/machines> should show a `searxng` device (green).

## Operations

### Access

```text
https://searxng.tail57bf10.ts.net
```

(Or `https://searxng` if MagicDNS is enabled in your tailnet.)

### Update

```bash
# Either component
kubectl rollout restart deployment searxng -n searxng

# Or pin a version
kubectl set image deployment/searxng \
  searxng=searxng/searxng:2026.04 -n searxng
```

### Rotate Tailscale auth key (every 90 days)

```bash
sops k8s/apps/searxng/secret.yaml      # update authkey
kubectl rollout restart deployment/searxng -n searxng
```

The PVC retains the tailnet identity, so the new auth key just refreshes the session — the device keeps the same node ID.

### Backup tailnet state

The PVC is on `local-path-provisioner` on rasp-pi-03 (`/var/lib/rancher/k3s/storage/...`). For a snapshot:
```bash
ssh rasp-pi-03 "sudo tar -C /var/lib/rancher/k3s/storage \
  -czf /tmp/searxng-ts-state-$(date +%F).tgz pvc-searxng-tailscale-state-*"
```

## Troubleshooting

### Pod shows 1/2 Ready

Identify which container failed:
```bash
kubectl describe pod -n searxng -l app=searxng
kubectl logs -n searxng -l app=searxng -c tailscale
kubectl logs -n searxng -l app=searxng -c searxng
```

Most common: invalid or expired auth key. Generate a new one and update the secret (see Operations above).

### Tailscale node not appearing in admin console

```bash
kubectl logs -n searxng -l app=searxng -c tailscale -f
```

Check for `authentication failed` (key expired/wrong) or network egress issues (a NetworkPolicy could block outbound 443).

### `https://searxng` doesn't resolve

- Confirm MagicDNS is enabled in the tailnet (<https://login.tailscale.com/admin/dns>)
- Check sidecar logs for `serve` mentions: `kubectl logs ... -c tailscale | grep -i serve`
- Test direct: `kubectl port-forward -n searxng svc/searxng-service 8080:8080` then `http://localhost:8080`

### OOMKilled

Combined limit is 528Mi. If sustained, bump cautiously — rasp-pi-03 has very little headroom. Check `kubectl top pod -n searxng --containers` to see which container is hot.

### Pod stuck `Pending`

Almost always: rasp-pi-03 isn't `Ready` or the `kubernetes.io/hostname: rasp-pi-03` selector doesn't match. Check `kubectl describe pod -n searxng <pod>`.

## Security

- Zero public exposure — accessible only via tailnet
- TLS terminated by the sidecar (Tailscale-managed certs)
- Tailscale runs in **userspace mode** (`TS_USERSPACE=true`) — no `NET_ADMIN` capability needed
- Both containers run non-root
- Secret keys in Kubernetes Secrets (SOPS-encrypted in git)

ACL example (Tailscale console):
```json
{
  "tagOwners": { "tag:searxng": ["you@example.com"] },
  "acls": [
    { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:searxng:443"] }
  ]
}
```

## Related

- **Tailscale operator (preferred for new apps):** [`tailscale-operator.md`](tailscale-operator.md)
- **All ingress hostnames:** [`../reference/tailnet-services.md`](../reference/tailnet-services.md)
- **Networking model:** [`../architecture/networking.md`](../architecture/networking.md)
