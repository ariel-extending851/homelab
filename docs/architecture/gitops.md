# GitOps with ArgoCD

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

ArgoCD is the only thing that mutates Kubernetes resources after `make ansible-deploy` finishes. It runs an App-of-Apps pattern with SOPS decryption baked into `argocd-repo-server`.

---

## Topology

```text
homelab-apps-root (the only manually-applied Application)
    └── watches k8s/apps/  (Kustomize directory)
        ├── adguard
        ├── golink
        ├── grafana
        ├── ... (16 apps total)
```

`homelab-apps-root` is a single Application defined in [`k8s/gitops/apps-root.yaml`](../../k8s/gitops/apps-root.yaml). It watches the [`k8s/apps/`](../../k8s/apps/) directory; ArgoCD auto-detects the per-app `kustomization.yaml` files and creates child Applications for each.

## Sync Policy

The root Application is configured with:

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
    - ApplyOutOfSyncOnly=true
    - ServerSideApply=true
  retry:
    limit: 5
    backoff:
      duration: 5s
      maxDuration: 3m
      factor: 2
```

Plain English: "If git changes, sync. If the cluster diverges, fix it. If a manifest disappears from git, delete the live resource last (after the others are reconciled). Retry up to 5 times with exponential backoff."

## Ignored Differences

Two things ArgoCD is told **not** to consider drift:

```yaml
ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers: ["/spec/replicas"]            # HPA-managed
  - kind: Secret
    jsonPointers: ["/data"]                      # SOPS-managed (decrypted at sync time)
```

## Repository Configuration

ArgoCD pulls from `git@github.com:ariel-extending851/homelab.git` (branch `develop`). Authentication uses an **SSH deploy key**:

| File | Purpose |
|---|---|
| [`k8s/gitops/ssh/argocd`](../../k8s/gitops/ssh/) | ED25519 private key (gitignored) |
| [`k8s/gitops/ssh/argocd.pub`](../../k8s/gitops/ssh/) | Public key (also gitignored, but safe to share) |
| [`k8s/gitops/argocd-repo-ssh-secret.yaml`](../../k8s/gitops/argocd-repo-ssh-secret.yaml) | Wraps the private key into the Secret ArgoCD reads |

### One-time setup

1. Generate the keypair:
   ```bash
   ssh-keygen -t ed25519 -C "argocd@homelab-cluster-$(date +%Y)" \
     -f k8s/gitops/ssh/argocd -N ""
   ```
2. Copy the public key:
   ```bash
   cat k8s/gitops/ssh/argocd.pub
   ```
3. Paste at <https://github.com/ariel-extending851/homelab/settings/keys/new>
   - **Title:** `ArgoCD Deploy Key (Read-Only)`
   - **Allow write access:** ❌ unchecked
4. Apply the Secret:
   ```bash
   kubectl apply -f k8s/gitops/argocd-repo-ssh-secret.yaml
   ```
5. Force ArgoCD to refresh:
   ```bash
   kubectl patch application homelab-apps-root -n argocd --type merge \
     -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'
   ```

### Annual key rotation

```bash
ssh-keygen -t ed25519 -C "argocd@homelab-cluster-$(date +%Y)" \
  -f k8s/gitops/ssh/argocd -N ""
# Update the GitHub deploy key (replace old)
kubectl delete secret -n argocd argocd-repo-homelab
kubectl apply -f k8s/gitops/argocd-repo-ssh-secret.yaml
# Force refresh as above
```

## SOPS Decryption at Sync

`argocd-repo-server` runs with a **SOPS sidecar** (the "CMP plugin") that decrypts SOPS-encrypted Secret manifests during `kustomize build`. The age private key is mounted from the `sops-age` Secret in the `argocd` namespace, which the Ansible `argocd` role provisions on first install.

Architecture model: [`secrets-management.md`](secrets-management.md). Workstation setup: [`../operations/sops-setup.md`](../operations/sops-setup.md).

## Daily Workflow

| Action | How |
|---|---|
| Add a new app | Drop a directory under `k8s/apps/<name>/` with a `kustomization.yaml`. Commit + push. ArgoCD picks it up automatically. |
| Update an app's image tag | Edit `kustomization.yaml` (or the manifest), commit, push. Sync happens within ~3 min, sooner if you bump the refresh annotation. |
| Rotate a secret | Edit with `sops k8s/apps/<app>/secret.yaml`, commit, push. SOPS sidecar decrypts at sync. |
| Force a sync | `kubectl patch application <name> -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'` |
| Wait for sync (CI) | `make validate-argocd-synced` blocks until the root app is `Synced + Healthy` |
| Open the UI | `make argocd-port-forward` then <https://localhost:8080> |
| Get admin password | `make argocd-password` |

## Verifying GitOps Is Working

```bash
# Repo-server should show 2/2 (main + sops-plugin sidecar)
kubectl get pods -n argocd

# Root app should be Synced + Healthy
kubectl get application homelab-apps-root -n argocd

# Per-child status
kubectl get applications -n argocd
```

If `homelab-apps-root` is `OutOfSync`, the most common cause is the SSH deploy key changed in GitHub or the `sops-age` Secret was rotated without updating ArgoCD's mount. See [`../runbooks/control-plane-recovery.md`](../runbooks/control-plane-recovery.md) for the recovery flow.

## Related

- **Cluster bootstrap (the Ansible side):** [`../operations/ansible.md#argocd-bootstrap-phase-2-detail`](../operations/ansible.md#argocd-bootstrap-phase-2-detail)
- **Secrets model:** [`secrets-management.md`](secrets-management.md)
- **SOPS workflow:** [`../operations/sops-setup.md`](../operations/sops-setup.md)
- **K8s overall architecture:** [`kubernetes.md`](kubernetes.md)
