# Tailscale Migration Summary

This document summarizes the migration from Tailscale sidecar pattern to the Tailscale Kubernetes Operator.

## Migration Overview

**Date:** January 22, 2026  
**Strategy:** Replace manual sidecars with native Kubernetes Ingress  
**Tailnet:** `tail57bf10.ts.net`

## What Changed

### System Level

**New:** `k8s/system/tailscale-operator/`
- `namespace.yaml` - Tailscale operator namespace
- `secret.yaml` - OAuth credentials (requires manual configuration)
- `rbac.yaml` - ClusterRole, ClusterRoleBinding, Role, RoleBinding
- `deployment.yaml` - Operator deployment
- `ingressclass.yaml` - IngressClass resource for `tailscale`
- `kustomization.yaml` - Kustomize manifest
- `README.md` - Installation and usage guide

### Application Level Changes

#### 1. Grafana (`k8s/apps/grafana/`)
**Removed:**
- Tailscale sidecar container (lines 25-78 in deployment.yaml)
- Tailscale state volume and PVC
- `grafana-tailscale-state` PVC from pvc.yaml

**Added:**
- `ingress.yaml` with `ingressClassName: tailscale`
- Hostname: `grafana.tail57bf10.ts.net`

**Updated:**
- `kustomization.yaml` - added `ingress.yaml` resource

---

#### 2. Prometheus (`k8s/apps/prometheus/`)
**Removed:**
- Tailscale sidecar container (lines 26-77 in deployment.yaml)
- Tailscale state volume and PVC
- `prometheus-tailscale-state` PVC from pvc.yaml

**Added:**
- `ingress.yaml` with `ingressClassName: tailscale`
- Hostname: `prometheus.tail57bf10.ts.net`

**Updated:**
- `kustomization.yaml` - added `ingress.yaml` resource

---

#### 3. Loki (`k8s/apps/loki/`)
**Removed:**
- Tailscale sidecar container (lines 26-77 in deployment.yaml)
- Tailscale state volume and PVC
- `loki-tailscale-state` PVC from pvc.yaml

**Added:**
- `ingress.yaml` with `ingressClassName: tailscale`
- Hostname: `loki.tail57bf10.ts.net`

**Updated:**
- `kustomization.yaml` - added `ingress.yaml` resource

---

#### 4. AdGuard (`k8s/apps/adguard/`)
**Removed:**
- Tailscale sidecar container (lines 29-81 in deployment.yaml)
- Tailscale state volume and PVC
- `adguard-tailscale-state` PVC from pvc.yaml

**Added:**
- `ingress.yaml` with `ingressClassName: tailscale`
- Hostname: `adguard.tail57bf10.ts.net`

**Updated:**
- `kustomization.yaml` - added `ingress.yaml` resource

---

#### 5. SearXNG (`k8s/apps/searxng/`)
**Removed:**
- Tailscale sidecar container (lines 129-174 in deployment.yaml)
- Tailscale state volume and PVC
- `hl-searxng-tailscale-state` PVC from deployment.yaml
- `searxng-tailscale-auth` secret from deployment.yaml

**Modified:**
- `ingress.yaml` - changed from Traefik to Tailscale
  - Before: `kubernetes.io/ingress.class: traefik`, `searxng.local`
  - After: `ingressClassName: tailscale`, `searxng.tail57bf10.ts.net`

**Added:**
- `kustomization.yaml` (new file)

---

#### 6. GoLink (`k8s/apps/golink/`)
**Removed:**
- Tailscale environment variables from deployment.yaml:
  - `TS_AUTHKEY`
  - `TS_STATE_DIR`
  - `TS_HOSTNAME`
  - `TS_ACCEPT_DNS`

**Modified:**
- `ingress.yaml` - changed from Traefik to Tailscale
  - Before: `kubernetes.io/ingress.class: traefik`, `golink.local`
  - After: `ingressClassName: tailscale`, `golink.tail57bf10.ts.net`

**Kept:**
- PVC for GoLink database (not Tailscale-related)
- RBAC (ServiceAccount only, not Tailscale-related)

## Resource Savings

### Per Application (approximate)
- **CPU:** Saved 50m request, 200m limit
- **Memory:** Saved 64Mi request, 128Mi limit
- **Storage:** Saved 100Mi PVC per app

### Total Cluster Savings
- **Applications migrated:** 6 (Grafana, Prometheus, Loki, AdGuard, SearXNG, GoLink)
- **CPU saved:** ~300m requests, ~1200m limits
- **Memory saved:** ~384Mi requests, ~768Mi limits
- **Storage saved:** ~600Mi (6 × 100Mi PVCs removed)

## Deployment Order

1. **Deploy Operator First:**
   ```bash
   # Configure OAuth secret
   kubectl create secret generic operator-oauth \
     --from-literal=client_id=<CLIENT_ID> \
     --from-literal=client_secret=<CLIENT_SECRET> \
     -n tailscale
   
   # Deploy operator
   kubectl apply -k k8s/system/tailscale-operator/
   
   # Verify
   kubectl get pods -n tailscale
   kubectl get ingressclass tailscale
   ```

2. **Migrate Applications:**
   ```bash
   # Delete old deployments (this will clean up sidecar pods)
   kubectl delete deployment grafana -n grafana
   kubectl delete deployment prometheus -n prometheus
   kubectl delete deployment loki -n loki
   kubectl delete deployment adguardhome -n adguard
   kubectl delete deployment searxng -n searxng
   kubectl delete deployment golink -n golink
   
   # Delete old Tailscale-related PVCs
   kubectl delete pvc grafana-tailscale-state -n grafana
   kubectl delete pvc prometheus-tailscale-state -n prometheus
   kubectl delete pvc loki-tailscale-state -n loki
   kubectl delete pvc adguard-tailscale-state -n adguard
   kubectl delete pvc hl-searxng-tailscale-state -n searxng
   
   # Delete old Tailscale auth secrets
   kubectl delete secret tailscale-auth -n grafana
   kubectl delete secret tailscale-auth -n prometheus
   kubectl delete secret tailscale-auth -n loki
   kubectl delete secret tailscale-auth -n adguard
   kubectl delete secret searxng-tailscale-auth -n searxng
   kubectl delete secret tailscale-auth-key -n golink
   
   # Apply updated manifests
   kubectl apply -k k8s/apps/grafana/
   kubectl apply -k k8s/apps/prometheus/
   kubectl apply -k k8s/apps/loki/
   kubectl apply -k k8s/apps/adguard/
   kubectl apply -k k8s/apps/searxng/
   kubectl apply -k k8s/apps/golink/
   ```

3. **Verify Migration:**
   ```bash
   # Check all ingresses
   kubectl get ingress -A
   
   # Check Tailscale devices
   # Visit: https://login.tailscale.com/admin/machines
   
   # Test access (from a device on the Tailnet)
   curl https://grafana.tail57bf10.ts.net
   curl https://prometheus.tail57bf10.ts.net
   curl https://loki.tail57bf10.ts.net
   curl https://adguard.tail57bf10.ts.net
   curl https://searxng.tail57bf10.ts.net
   curl https://golink.tail57bf10.ts.net
   ```

## Rollback Plan

If migration fails:

1. **Revert to sidecar pattern:**
   ```bash
   # Checkout previous Git commit
   git checkout <previous-commit>
   
   # Delete operator ingresses
   kubectl delete ingress -n grafana grafana-ingress
   kubectl delete ingress -n prometheus prometheus-ingress
   kubectl delete ingress -n loki loki-ingress
   kubectl delete ingress -n adguard adguard-ingress
   kubectl delete ingress -n searxng searxng-ingress
   kubectl delete ingress -n golink golink-ingress
   
   # Reapply old manifests
   kubectl apply -k k8s/apps/grafana/
   kubectl apply -k k8s/apps/prometheus/
   kubectl apply -k k8s/apps/loki/
   kubectl apply -k k8s/apps/adguard/
   kubectl apply -k k8s/apps/searxng/
   kubectl apply -k k8s/apps/golink/
   ```

2. **Optional: Remove operator**
   ```bash
   kubectl delete -k k8s/system/tailscale-operator/
   ```

## Post-Migration Cleanup

After successful migration:

1. **Remove orphaned Tailscale devices:**
   - Visit: https://login.tailscale.com/admin/machines
   - Delete old sidecar devices: `grafana`, `prometheus`, `loki`, `adguard`, `searxng`, `golink`

2. **Verify no orphaned resources:**
   ```bash
   # Check for unused PVCs
   kubectl get pvc -A | grep tailscale
   
   # Check for unused secrets
   kubectl get secrets -A | grep tailscale
   ```

## Known Issues & Considerations

1. **GoLink Image:** The official `ghcr.io/tailscale/golink:main` image includes Tailscale. When using the operator, the built-in Tailscale functionality is bypassed via the Ingress resource.

2. **AdGuard DNS:** AdGuard uses `hostNetwork: true` for LAN DNS service. The Tailscale ingress only exposes the admin UI (port 3000), not DNS (port 53).

3. **TLS Certificates:** The operator automatically manages TLS certificates. You no longer need to handle this manually.

4. **Hostname Pattern:** All services use `<app>.tail57bf10.ts.net` format for consistency.

## References

- [Tailscale Kubernetes Operator Documentation](https://tailscale.com/kb/1236/kubernetes-operator)
- [Original Homelab Deployment Docs](../apps/DEPLOYMENT.md)
