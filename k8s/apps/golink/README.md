# GoLink Deployment

This directory will contain Kubernetes manifests for deploying GoLink (by Tailscale) for internal URL shortening (go/links).

## Requirements
- Tailscale Auth Key Secret (must be configured in the cluster)
  - Expected secret name: `tailscale-auth-key`
  - Expected key in secret: `authkey`

## Technical Considerations: K8s vs Systemd Deployment

### Running GoLink in Kubernetes (Recommended for GitOps)

**Pros:**
- **GitOps Alignment**: Manifests in version control enable declarative, auditable deployments via ArgoCD
- **Consistency**: Same deployment pattern as other services (SearXNG, monitoring stack)
- **Portability**: Can migrate between nodes without manual reconfiguration
- **Secret Management**: Leverage Kubernetes Secrets for Tailscale Auth Key
- **Health Monitoring**: Native liveness/readiness probes and restart policies
- **Resource Controls**: CPU/memory limits prevent resource exhaustion on RPi3
- **Updates**: Rolling updates with zero downtime via Deployment strategy

**Cons:**
- Additional overhead from container runtime and kubelet
- Slightly more complex networking (though Tailscale runs in userspace)

### Running GoLink as Systemd Service

**Pros:**
- Lower resource overhead (minimal abstraction)
- Direct systemd integration for service management

**Cons:**
- **Breaks GitOps Model**: Manual configuration required on each deployment/update
- **No Version Control**: Service configuration not in Git
- **Manual Updates**: Must SSH to RPi3 for changes
- **Poor Auditability**: Changes not tracked in version control
- **Inconsistent Architecture**: Deviates from cluster-based approach

## Recommendation

**Deploy GoLink in Kubernetes** to maintain GitOps principles and architectural consistency. The overhead is minimal for a lightweight Go application, and the benefits of declarative management, version control, and automated deployments far outweigh the marginal resource savings of running it as a bare systemd service.

The Tailscale-first network strategy works seamlessly with Kubernetes pods, as Tailscale can run as a sidecar or use the host's Tailscale connection.

## Deployment

### Prerequisites

1. **Generate Tailscale Auth Key**:
   ```bash
   # Visit https://login.tailscale.com/admin/settings/keys
   # Create a new auth key with:
   #   - Reusable: No (one-time use for security)
   #   - Ephemeral: No (persist across pod restarts)
   #   - Pre-approved: Yes
   #   - Tags: tag:golink (recommended)
   ```

2. **Create the Secret**:
   ```bash
   kubectl create secret generic tailscale-auth-key \
     --from-literal=authkey=tskey-auth-XXXXXXXXXXXX-YYYYYYYYYYYYYYYYYYYY \
     -n golink
   ```

   **Important**: Delete `secret.yaml` from your apply command if you created the secret manually, or replace the placeholder in `secret.yaml` before deploying.

### Deploy GoLink

```bash
# Apply all manifests
kubectl apply -k k8s/apps/golink/

# Verify deployment
kubectl get pods -n golink
kubectl logs -n golink -l app=golink
```

### Access GoLink

Once deployed, GoLink will be available at:
- **Internal DNS**: `http://golink.local` (via Traefik Ingress)
- **Tailscale MagicDNS**: `http://golink` (if MagicDNS is enabled in your tailnet)

### Resource Allocation

**Configured Limits** (optimized for RPi3):
- CPU Request: 50m, Limit: 200m
- Memory Request: 64Mi, Limit: 128Mi
- Storage: 1Gi PVC for SQLite database

### Security Hardening

This deployment follows AWS DevOps Professional (DOP-C02) best practices:
- ✅ **Non-root execution**: Runs as user 65532
- ✅ **Dropped capabilities**: All Linux capabilities dropped
- ✅ **Resource constraints**: Strict CPU/memory limits
- ✅ **Health checks**: Liveness and readiness probes configured
- ✅ **Least privilege**: Dedicated ServiceAccount with minimal permissions

## Troubleshooting

**Pod not starting:**
```bash
# Check pod status and events
kubectl describe pod -n golink -l app=golink

# Check logs
kubectl logs -n golink -l app=golink
```

**Common issues:**
1. **Invalid Tailscale auth key**: Verify the secret is correctly created
2. **PVC not binding**: Check if local-path provisioner is running (default in k3s)
3. **Resource limits**: If pod is OOMKilled, increase memory limits cautiously
