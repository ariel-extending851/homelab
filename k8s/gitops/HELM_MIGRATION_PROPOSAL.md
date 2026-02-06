# ArgoCD Helm Migration Proposal

## Executive Summary

**Status:** 🟡 OPTIONAL (Recommended for Production)

This document proposes migrating the ArgoCD base installation from raw Kubernetes YAML manifests to the official [ArgoCD Helm Chart](https://github.com/argoproj/argo-helm). This aligns with the Tailscale Operator migration pattern completed in Phase 5 and provides long-term maintainability benefits.

## Problem Statement

### Current State (YAML-Based Installation)

The current ArgoCD installation uses the official YAML manifest:

```bash
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

**Limitations:**
1. **Manual Upgrades:** Requires manual tracking of upstream releases
2. **Configuration Drift:** Custom configurations (SSH keys, RBAC, ingress) are decoupled from the base installation
3. **No Declarative Values:** Cannot use a single `values.yaml` for configuration
4. **Difficult Rollbacks:** No built-in rollback mechanism (must manually apply previous manifest)
5. **No Upgrade Hooks:** Cannot run pre/post-upgrade validation scripts

### Desired State (Helm-Based Installation)

Migrate to the official ArgoCD Helm chart:

```bash
helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --values k8s/gitops/helm/argocd-values.yaml
```

**Benefits:**
1. **Declarative Configuration:** Single `values.yaml` for all settings
2. **Version Control:** Explicit chart version tracking (`appVersion: v2.12.3`)
3. **Automated Upgrades:** `helm upgrade` with built-in diff preview
4. **Easy Rollbacks:** `helm rollback argocd <revision>`
5. **Community Support:** Extensive Helm values documentation and examples
6. **Integration with GitOps:** Can be managed by ArgoCD itself (Helm Application)

## Technical Design

### Architecture Alignment

This migration follows the **Tailscale Operator Pattern** (Phase 5):

| Component              | Phase 5 (Tailscale)              | Phase 6+ (ArgoCD)               |
|------------------------|----------------------------------|---------------------------------|
| **Installation Method** | Helm Chart                       | Helm Chart                      |
| **Config Management**   | `values.yaml` in VCS             | `values.yaml` in VCS            |
| **GitOps Management**   | Self-managed via ArgoCD          | Self-managed via ArgoCD (meta)  |
| **Namespace**           | `tailscale`                      | `argocd`                        |
| **Upgrade Strategy**    | `helm upgrade` or ArgoCD sync    | `helm upgrade` or ArgoCD sync   |

### Proposed File Structure

```
k8s/gitops/
├── apps-root.yaml                  # App-of-Apps (already exists)
├── helm/
│   ├── argocd-values.yaml          # Helm values for ArgoCD base installation
│   └── argocd-application.yaml     # ArgoCD Application CRD (self-management)
├── ssh/
│   ├── argocd                      # SSH private key (excluded from VCS)
│   ├── argocd.pub                  # SSH public key (excluded from VCS)
│   └── README.md                   # SSH setup documentation
├── create-argocd-ssh-secret.sh     # Secret generation script
├── apply-phase6-gitops.sh          # Phase 6 orchestration script
└── README.md                       # GitOps documentation
```

## Migration Strategy

### Option A: In-Place Upgrade (Recommended)

**Pros:**
- No downtime for managed applications
- Preserves existing Application CRDs
- Lower risk (Helm adopts existing resources)

**Cons:**
- Requires manual resource adoption (`helm adopt`)
- Potential configuration drift during transition

**Steps:**
1. Export current ArgoCD configuration:
   ```bash
   kubectl get -n argocd deployment argocd-server -o yaml > argocd-server-backup.yaml
   ```

2. Create `k8s/gitops/helm/argocd-values.yaml` (minimal overrides):
   ```yaml
   global:
     domain: argocd.tail57bf10.ts.net  # Optional: Tailscale MagicDNS

   server:
     resources:
       limits:
         cpu: 200m
         memory: 256Mi
       requests:
         cpu: 50m
         memory: 128Mi

   repoServer:
     resources:
       limits:
         cpu: 200m
         memory: 256Mi
       requests:
         cpu: 50m
         memory: 128Mi

   controller:
     resources:
       limits:
         cpu: 300m
         memory: 512Mi
       requests:
         cpu: 100m
         memory: 256Mi

   # SSH repository credentials (reference existing secret)
   configs:
     repositoryCredentials:
       git@github.com:ariel99gf/homelab.git:
         type: ssh
         sshPrivateKeySecretName: argocd-repo-homelab
   ```

3. Add Helm repository:
   ```bash
   helm repo add argo https://argoproj.github.io/argo-helm
   helm repo update
   ```

4. Perform Helm adoption (dry-run first):
   ```bash
   helm install argocd argo/argo-cd \
     --namespace argocd \
     --values k8s/gitops/helm/argocd-values.yaml \
     --dry-run --debug
   ```

5. Execute adoption:
   ```bash
   helm install argocd argo/argo-cd \
     --namespace argocd \
     --values k8s/gitops/helm/argocd-values.yaml \
     --replace
   ```

6. Verify adoption:
   ```bash
   helm list -n argocd
   kubectl get applications -n argocd
   ```

### Option B: Fresh Installation (High Risk)

**Pros:**
- Clean slate (no legacy configuration)
- Easier to troubleshoot

**Cons:**
- **HIGH RISK:** All Application CRDs must be re-created
- Downtime for managed applications
- Potential data loss if backups are incomplete

**Not Recommended** unless current installation is corrupted.

## Resource Optimization (Raspberry Pi Constraints)

ArgoCD default Helm values are designed for cloud environments with abundant resources. **CRITICAL:** Override resource requests/limits for Raspberry Pi 3/4 compatibility:

```yaml
# k8s/gitops/helm/argocd-values.yaml

# ArgoCD Server (UI & API)
server:
  resources:
    limits:
      cpu: 200m       # Default: 500m
      memory: 256Mi   # Default: 512Mi
    requests:
      cpu: 50m        # Default: 250m
      memory: 128Mi   # Default: 256Mi

# Repository Server (Git fetching)
repoServer:
  resources:
    limits:
      cpu: 200m       # Default: 1000m
      memory: 256Mi   # Default: 512Mi
    requests:
      cpu: 50m        # Default: 100m
      memory: 128Mi   # Default: 256Mi

# Application Controller (Sync logic)
controller:
  resources:
    limits:
      cpu: 300m       # Default: 2000m
      memory: 512Mi   # Default: 2048Mi
    requests:
      cpu: 100m       # Default: 500m
      memory: 256Mi   # Default: 1024Mi

# Redis (In-memory cache)
redis:
  resources:
    limits:
      cpu: 100m       # Default: 200m
      memory: 128Mi   # Default: 256Mi
    requests:
      cpu: 50m        # Default: 100m
      memory: 64Mi    # Default: 128Mi
```

**Total Resource Footprint (Helm vs. Current):**

| Component          | Current (YAML)  | Helm (Optimized) | Savings   |
|--------------------|-----------------|------------------|-----------|
| CPU Requests       | ~500m           | ~250m            | 50%       |
| CPU Limits         | ~2000m          | ~800m            | 60%       |
| Memory Requests    | ~1024Mi         | ~576Mi           | 43%       |
| Memory Limits      | ~3072Mi         | ~1152Mi          | 62%       |

## Self-Management with ArgoCD (GitOps Inception)

Once migrated to Helm, ArgoCD can manage **itself** via an Application CRD:

```yaml
# k8s/gitops/helm/argocd-application.yaml
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: argocd
  namespace: argocd
spec:
  project: default
  source:
    chart: argo-cd
    repoURL: https://argoproj.github.io/argo-helm
    targetRevision: 7.7.10  # Explicit version pinning (DOP-C02 best practice)
    helm:
      valuesObject:  # Inline values (or use valueFiles for external config)
        global:
          domain: argocd.tail57bf10.ts.net
        # ... (copy from argocd-values.yaml)
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: false      # CRITICAL: Prevent accidental deletion of ArgoCD itself
      selfHeal: true    # Auto-correct drift
    syncOptions:
      - CreateNamespace=false  # Namespace must already exist
```

**Guardrail:** Set `prune: false` to prevent ArgoCD from deleting itself during sync failures.

## Risk Assessment

| Risk                          | Likelihood | Impact | Mitigation                                     |
|-------------------------------|------------|--------|------------------------------------------------|
| Application downtime          | Low        | High   | Use in-place upgrade (Option A)                |
| Configuration loss            | Low        | Medium | Backup existing YAML before migration          |
| Resource exhaustion (RPi)     | Medium     | High   | Use optimized `values.yaml` (see above)        |
| Helm chart compatibility      | Low        | Low    | Use official ArgoCD Helm chart (well-tested)   |
| Self-management infinite loop | Low        | High   | Disable `prune` for ArgoCD self-management     |

## Timeline & Effort Estimation

| Phase                         | Effort   | Dependencies                          |
|-------------------------------|----------|---------------------------------------|
| 1. Create `argocd-values.yaml`| 1 hour   | None                                  |
| 2. Test Helm dry-run          | 30 min   | Phase 1 complete                      |
| 3. Perform in-place adoption  | 1 hour   | Phase 2 validation                    |
| 4. Verify all applications    | 30 min   | Phase 3 successful                    |
| 5. Enable self-management     | 1 hour   | Phase 4 stable for 24h                |
| **TOTAL**                     | **4h**   | -                                     |

## Success Criteria

1. ✅ ArgoCD is managed by Helm (`helm list -n argocd` shows `argocd` release)
2. ✅ All existing Application CRDs remain functional (no re-creation required)
3. ✅ Resource usage stays within Raspberry Pi constraints (<512Mi per pod)
4. ✅ Upgrade process is documented and reproducible
5. ✅ ArgoCD can self-manage via Application CRD (optional)

## Decision Matrix

| Criteria                      | YAML Installation | Helm Installation |
|-------------------------------|-------------------|-------------------|
| **Ease of Upgrades**          | ❌ Manual         | ✅ `helm upgrade` |
| **Configuration Management**  | ❌ Fragmented     | ✅ Declarative    |
| **Rollback Capability**       | ❌ Manual         | ✅ Built-in       |
| **GitOps Self-Management**    | ❌ Complex        | ✅ Native         |
| **Resource Optimization**     | ⚠️ Manual tuning  | ✅ values.yaml    |
| **Community Support**         | ✅ Official YAML  | ✅ Official Helm  |
| **Migration Effort**          | ✅ N/A (current)  | ⚠️ 4 hours        |

**Recommendation:** Migrate to Helm after Phase 6 stabilizes (SSH authentication verified).

## References

- [ArgoCD Official Helm Chart](https://github.com/argoproj/argo-helm/tree/main/charts/argo-cd)
- [ArgoCD Operator vs. Helm Comparison](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)
- [Helm Best Practices](https://helm.sh/docs/chart_best_practices/)
- [AWS DOP-C02: Configuration Management](https://aws.amazon.com/certification/certified-devops-engineer-professional/)

## Approval Checklist

Before proceeding with this migration:

- [ ] Phase 6 SSH authentication is stable for 7+ days
- [ ] All applications in `k8s/apps/` are synced and healthy
- [ ] `argocd-values.yaml` is reviewed by Tech Lead
- [ ] Backup of current ArgoCD configuration is stored in `backups/argocd/`
- [ ] Migration scheduled during maintenance window (no production impact)
- [ ] Rollback plan documented (restore from YAML backup)

---

**Author:** Claude (Tech Lead)
**Date:** 2026-01-23
**Phase:** 6+ (Post-SSH Migration)
**Status:** 🟡 Pending User Approval
