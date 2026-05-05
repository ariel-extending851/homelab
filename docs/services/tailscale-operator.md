# Tailscale Operator

> **Status:** Active · **Namespace:** tailscale · **Type:** system component
> **Manifests:** [`k8s/system/tailscale-operator/`](../../k8s/system/tailscale-operator/) · **Last reviewed:** 2026-04-23

The [Tailscale Kubernetes Operator](https://tailscale.com/kb/1185/kubernetes/) provides the `tailscale` IngressClass that exposes every public-facing app on the tailnet. Installed via Helm (not pure Kustomize).

## Overview

Without the operator, getting Kubernetes Services onto a tailnet requires a sidecar Tailscale pod per app. The operator automates this: any `Ingress` with `ingressClassName: tailscale` automatically gets a backing proxy pod and a tailnet hostname.

## Architecture

- **Namespace:** `tailscale`
- **Components:**
  - `operator` Deployment (watches Ingress + Service resources)
  - `proxy` pods named `ts-<ingress-name>` (one per Ingress, ephemeral)
- **Auth:** OAuth client credentials in a Helm-managed Secret
- **Tags:** every operator-created tailnet device gets `tag:k8s-operator`

## Installation

The operator is installed by the **`tailscale_operator` ansible role**, wired into `site.yml` as Phase 2.3 (after ArgoCD is up). A clean `make ansible-deploy` brings it up automatically — no manual `helm` step required.

```bash
# Bundled into the full deploy:
make ansible-deploy

# Or, run just the operator install (useful when adding/upgrading):
ansible-playbook -i ansible/inventory/production.yml \
  -i ansible/terraform_inventory_aws.py \
  ansible/playbooks/system/install_tailscale_operator.yml
```

The role:
1. Verifies `helm` is available on the controller and the kubeconfig at `/tmp/k3s-homelab-kubeconfig.yaml` exists (`site.yml`'s pre-flight populates it).
2. Adds the upstream `tailscale` Helm repo and refreshes its index.
3. Decrypts `k8s/system/tailscale-operator/values.sops.yaml` (OAuth credentials) into a 0600 tempfile on the controller.
4. Runs `helm upgrade --install tailscale-operator tailscale/tailscale-operator -f values.yaml -f <decrypted-tempfile> --wait` against the cluster.
5. Removes the tempfile.
6. Applies `proxyclass.yaml` and `high-bandwidth-proxyclass.yaml`.
7. Waits for the operator pod to reach `Running`.

OAuth credentials come from <https://login.tailscale.com/admin/settings/oauth> (scope: `auth_keys` + `devices`). Store them in `k8s/system/tailscale-operator/values.sops.yaml` (SOPS-encrypted) — see [`../operations/sops-setup.md`](../operations/sops-setup.md).

> **Why Helm and not Kustomize:** the upstream chart bundles the OAuth wiring and guards version compatibility tighter than a static manifest set would; running it through ansible keeps the install reproducible from a fresh cluster.

## Proxy Classes

The operator supports per-Service traffic shaping via `ProxyClass` resources:

| ProxyClass | Used by | Purpose |
|---|---|---|
| `default` | most apps | Standard bandwidth, single replica |
| `high-bandwidth` | grafana | Larger CPU/mem requests for dashboard/log streaming |

To opt in, label the Service:
```yaml
metadata:
  labels:
    tailscale.com/proxy-class: high-bandwidth
```

## Operations

### Upgrade

Re-run the operator playbook — the role's `helm upgrade --install` command is idempotent and will pick up any new chart version pinned in `k8s/system/tailscale-operator/values.yaml`:

```bash
ansible-playbook -i ansible/inventory/production.yml \
  -i ansible/terraform_inventory_aws.py \
  ansible/playbooks/system/install_tailscale_operator.yml
```

### Uninstall

```bash
helm uninstall tailscale-operator -n tailscale
```

This removes the operator + all proxies. Tailnet entries for the proxy devices remain until you prune them with `make clean-tailscale`.

### See active proxies

```bash
kubectl get pods -n tailscale | grep ^ts-
```

### Watch a new ingress get its proxy

```bash
kubectl apply -f k8s/apps/grafana/ingress.yaml
kubectl logs -n tailscale -l app=operator -f | grep -i grafana
```

## Troubleshooting

### Ingress created but no tailnet hostname appears
Check the operator logs:
```bash
kubectl logs -n tailscale -l app=operator --tail=100
```
Common: OAuth credentials missing the right scope, or tailnet ACLs blocking `tag:k8s-operator` from auto-approving.

### Proxy pod stuck in `CrashLoopBackOff`
The OAuth issuance probably failed. Check:
```bash
kubectl describe pod -n tailscale ts-<name> | grep -A5 'Last State'
```

### MagicDNS hostname collides
Two Ingresses can't claim the same hostname. The operator picks the first one and ignores the second. Look for warnings in operator logs.

## Migration History

Earlier versions of this homelab ran a Tailscale sidecar inside each app pod (`tailscale serve`). That was retired in January 2026 in favor of the operator pattern, which is cleaner and lets us share Tailscale auth + ACLs centrally. The migration writeup is archived in [`../archive/tailscale-sidecar-migration.md`](../archive/tailscale-sidecar-migration.md).

## Related

- **Networking architecture:** [`../architecture/networking.md`](../architecture/networking.md)
- **All ingress hostnames:** [`../reference/tailnet-services.md`](../reference/tailnet-services.md)
- **Recovery if tailnet auth fails:** [`../runbooks/tailscale-logged-out.md`](../runbooks/tailscale-logged-out.md)
