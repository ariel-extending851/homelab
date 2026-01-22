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

### Implementation Notes for Future Deployment
- Target namespace: TBD (recommend dedicated namespace or apps namespace)
- Resource limits: Should be constrained for RPi3 environment (e.g., 100m CPU, 128Mi memory)
- Integration: Will leverage existing cluster Tailscale configuration
- Storage: May require persistent volume for link database
