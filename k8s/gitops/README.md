# GitOps Configuration

This directory contains ArgoCD Application manifests that implement the App of Apps pattern.

## 📋 Quick Links

- **[Phase 6 Validation Guide](PHASE6_VALIDATION.md)** - Post-deployment validation steps
- **[Helm Migration Proposal](HELM_MIGRATION_PROPOSAL.md)** - Optional upgrade to Helm-based ArgoCD
- **[SSH Authentication Setup](ssh/README.md)** - GitHub Deploy Key configuration

## Prerequisites

1. **ArgoCD Installed:**
   ```bash
   kubectl create namespace argocd
   kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
   ```

2. **Wait for ArgoCD to be ready:**
   ```bash
   kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
   ```

3. **Get ArgoCD admin password:**
   ```bash
   kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
   ```

## Phase 6: SSH Authentication Setup (Recommended)

**Resolves OCI egress throttling by using SSH instead of HTTPS.**

### Automated Setup (Recommended)

```bash
# Execute the Phase 6 orchestration script
cd k8s/gitops
./apply-phase6-gitops.sh
```

This script will:
1. ✅ Guide you through adding the SSH Deploy Key to GitHub
2. ✅ Create the ArgoCD repository secret
3. ✅ Update the App-of-Apps to use SSH and the `develop` branch
4. ✅ Trigger ArgoCD refresh
5. ✅ Verify the migration

### Manual Setup (Alternative)

If you prefer manual configuration:

1. **Add SSH Deploy Key to GitHub:**
   ```bash
   cat k8s/gitops/ssh/argocd.pub
   # Add to: https://github.com/ariel99gf/homelab/settings/keys/new
   # Title: ArgoCD Deploy Key (Read-Only)
   # ✗ Uncheck "Allow write access"
   ```

2. **Create ArgoCD repository secret:**
   ```bash
   ./create-argocd-ssh-secret.sh
   ```

3. **Apply updated App-of-Apps:**
   ```bash
   kubectl apply -f k8s/gitops/apps-root.yaml
   ```

4. **Force ArgoCD refresh:**
   ```bash
   kubectl patch application homelab-apps-root -n argocd \
     --type merge \
     -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'
   ```

5. **Validate:** Follow the [Phase 6 Validation Guide](PHASE6_VALIDATION.md)

---

## Deploy App of Apps (Legacy HTTPS Method)

⚠️ **Warning:** HTTPS method is subject to OCI egress throttling. Use SSH method above.

Apply the root application that manages all apps in `k8s/apps/`:

```bash
kubectl apply -f k8s/gitops/apps-root.yaml
```

This will automatically:
- ✅ Discover all applications in `k8s/apps/` recursively
- ✅ Sync them to the cluster automatically
- ✅ Create namespaces as needed
- ✅ Auto-heal on configuration drift
- ✅ Prune deleted resources from Git

## Verify Deployment

```bash
# Check ArgoCD applications
kubectl get applications -n argocd

# Port-forward to ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Access UI at https://localhost:8080
# Username: admin
# Password: (from step 3 above)
```

## Architecture

```
homelab-apps-root (ArgoCD Application)
├── k8s/apps/prometheus/
├── k8s/apps/grafana/
├── k8s/apps/loki/
├── k8s/apps/blackbox/
├── k8s/apps/kube-state-metrics/
├── k8s/apps/node-exporter/
├── k8s/apps/otel-collector/
├── k8s/apps/searxng/
├── k8s/apps/golink/
└── k8s/apps/adguard/
```

Each subdirectory with a `kustomization.yaml` or raw manifests will be automatically discovered and synced.

## Troubleshooting

**Issue:** Application shows "OutOfSync"
```bash
# Force sync
kubectl patch application homelab-apps-root -n argocd --type merge -p '{"operation":{"sync":{}}}'
```

**Issue:** Namespace not created
- Ensure `CreateNamespace=true` is in `syncOptions`
- Check if namespace is defined in the app manifests

**Issue:** Resources not pruned
- Verify `prune: true` in `syncPolicy.automated`
- Check ArgoCD application events: `kubectl describe application homelab-apps-root -n argocd`
