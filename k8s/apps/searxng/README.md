# SearXNG Deployment for Raspberry Pi 3

This directory contains Kubernetes manifests for deploying SearXNG, a privacy-respecting metasearch engine, on the Raspberry Pi 3 node (rasp-pi-03) with **Tailscale sidecar integration**.

## Overview

SearXNG is deployed using the **Tailscale Sidecar Pattern**, enabling:
- ✅ **Direct HTTPS access** via Tailscale MagicDNS (`https://searxng`)
- ✅ **Automatic TLS termination** (no cert management required)
- ✅ **Zero-trust network access** (only accessible via your Tailnet)
- ✅ **Strict resource constraints** for Raspberry Pi 3 (~800MB free RAM)

## Architecture

```
[User] --HTTPS--> [Tailscale Network] --HTTPS:443--> [Tailscale Sidecar] --HTTP:8080--> [SearXNG Container]
                                                            (Pod on rasp-pi-03)
```

## Components

- **Namespace**: `searxng`
- **Secrets**:
  - `searxng-secret`: SearXNG application secret key
  - `searxng-tailscale-auth`: Tailscale authentication key
- **PersistentVolumeClaim**: Stores Tailscale state for identity persistence
- **ConfigMap**: SearXNG configuration settings
- **Deployment**: Multi-container pod with:
  - **Tailscale sidecar**: HTTPS proxy with MagicDNS
  - **SearXNG container**: Search engine application
- **Service**: ClusterIP service (legacy, primarily for Tailscale sidecar communication)
- **Ingress**: Traefik ingress (optional, legacy access via `searxng.local`)

## Resource Limits

The deployment uses strict resource limits suitable for Raspberry Pi 3:

**SearXNG Container:**
- **Memory Request**: 150Mi (conservative baseline)
- **Memory Limit**: 400Mi (strict cap to prevent OOM issues)
- **CPU Request**: 100m (minimal CPU reservation)
- **CPU Limit**: 500m (allows bursts but prevents monopolization)

**Tailscale Sidecar:**
- **Memory Request**: 64Mi
- **Memory Limit**: 128Mi
- **CPU Request**: 50m
- **CPU Limit**: 200m

**Total Pod Resources**: ~550Mi memory, ~700m CPU (comfortably fits RPi3 constraints)

## Prerequisites

1. **K3s cluster** must be running
2. **Node `rasp-pi-03`** must be available with label `kubernetes.io/hostname: rasp-pi-03`
3. **Tailscale account** with admin access to generate auth keys
4. **Traefik ingress controller** (optional, comes with K3s by default)

## Deployment Instructions

### 1. Generate Tailscale Auth Key

**CRITICAL**: You must create a Tailscale auth key before deployment.

1. Visit: https://login.tailscale.com/admin/settings/keys
2. Click **Generate auth key** with these settings:
   - **Reusable**: ✅ **Yes** (required for pod restarts)
   - **Ephemeral**: ❌ **No** (maintain persistent identity)
   - **Pre-approved**: ✅ **Yes** (auto-approve in ACLs)
   - **Tags**: `tag:k8s`, `tag:searxng` (recommended for ACL management)
   - **Expiration**: 90 days (or longer based on your security policy)

3. Copy the generated key (starts with `tskey-auth-...`)

### 2. Create Kubernetes Secrets

**Create the Tailscale auth secret:**

```bash
kubectl create secret generic searxng-tailscale-auth \
  --from-literal=authkey=tskey-auth-XXXXXXXXXXXX-YYYYYYYYYYYYYYYYYYYY \
  -n searxng
```

**⚠️ IMPORTANT**: Replace `tskey-auth-XXXXXXXXXXXX-YYYYYYYYYYYYYYYYYYYY` with your actual auth key!

**Create the SearXNG secret key:**

```bash
kubectl create secret generic searxng-secret \
  --from-literal=secret-key=$(openssl rand -hex 32) \
  -n searxng
```

**Alternative**: Manually edit the Secrets in `deployment.yaml` and replace the placeholders, then skip the `kubectl create secret` commands.

### 3. Apply the Manifests

Apply all manifests:

```bash
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
```

Or apply all at once:

```bash
kubectl apply -f .
```

### 4. Verify Deployment

```bash
# Check pod status (should show 2/2 containers ready)
kubectl get pods -n searxng

# Check if pod is running on rasp-pi-03
kubectl get pods -n searxng -o wide

# View SearXNG logs
kubectl logs -n searxng -l app=searxng -c searxng

# View Tailscale sidecar logs
kubectl logs -n searxng -l app=searxng -c tailscale

# Check PVC for Tailscale state
kubectl get pvc -n searxng
```

**Expected output:**
```
NAME      READY   STATUS    RESTARTS   AGE
searxng   2/2     Running   0          2m
```

### 5. Verify Tailscale Registration

Check that the `searxng` node appears in your Tailscale admin console:

1. Visit: https://login.tailscale.com/admin/machines
2. Look for a machine named **`searxng`**
3. Verify it's showing as **Connected** (green indicator)

### 6. Access SearXNG via Tailscale

**Primary Access Method (HTTPS via MagicDNS):**

```bash
# Access via MagicDNS (if enabled in your Tailnet)
https://searxng

# Or use the full Tailscale domain
https://searxng.<your-tailnet-name>.ts.net
```

**Legacy Access Method (HTTP via Ingress):**

If you still want to use the Traefik ingress, add to `/etc/hosts`:

```
<node-ip> searxng.local
```

Then access: `http://searxng.local`

**⚠️ Recommendation**: Use the Tailscale HTTPS endpoint for production. The ingress is maintained for backward compatibility only.

## Tailscale Sidecar Pattern

This deployment uses the **Tailscale Sidecar Pattern** for secure access:

**How it works:**
1. **Tailscale container** joins your Tailnet as a node named `searxng`
2. **Tailscale Serve** terminates HTTPS on port 443
3. **Traffic is proxied** to the SearXNG container on localhost:8080
4. **State persistence** via PVC ensures the node maintains its identity

**Benefits:**
- No ingress controller or load balancer required
- No certificate management (Tailscale handles TLS)
- No public IP or port forwarding needed
- Access controlled via Tailscale ACLs
- Works across NAT and firewalls

**Configuration:**
- `TS_USERSPACE=true`: No special kernel capabilities required
- `TS_SERVE_CONFIG`: JSON configuration for HTTPS proxy
- `TS_HOSTNAME=searxng`: Sets MagicDNS name
- `TS_EXTRA_ARGS`: Additional Tailscale flags (e.g., tags)

## Monitoring

**SearXNG Health Probes:**
- **Liveness Probe**: HTTP GET on `/` every 30s (prevents zombie processes)
- **Readiness Probe**: HTTP GET on `/` every 10s (ensures pod readiness)

**Tailscale Monitoring:**
- Check node status: https://login.tailscale.com/admin/machines
- View connection logs: `kubectl logs -n searxng -l app=searxng -c tailscale`
- Monitor resource usage: `kubectl top pod -n searxng`

## Troubleshooting

### Pod Shows 1/2 or 0/2 Ready

If only one container is running, check which container failed:

```bash
# Describe pod to see events
kubectl describe pod -n searxng -l app=searxng

# Check Tailscale container logs
kubectl logs -n searxng -l app=searxng -c tailscale

# Check SearXNG container logs
kubectl logs -n searxng -l app=searxng -c searxng
```

**Common issues:**

1. **Invalid Tailscale auth key**:
   - Error: `authentication failed` or `invalid auth key`
   - Solution: Verify the secret was created correctly with a valid auth key

2. **Auth key expired**:
   - Solution: Generate a new auth key and update the secret:
   ```bash
   kubectl delete secret searxng-tailscale-auth -n searxng
   kubectl create secret generic searxng-tailscale-auth \
     --from-literal=authkey=tskey-auth-NEW-KEY \
     -n searxng
   kubectl rollout restart deployment/searxng -n searxng
   ```

3. **PVC not binding**:
   - Check: `kubectl get pvc -n searxng`
   - Solution: Verify local-path provisioner is running (default in k3s)

### Tailscale Node Not Appearing in Admin Console

If the `searxng` node doesn't appear at https://login.tailscale.com/admin/machines:

```bash
# Check Tailscale container logs for authentication errors
kubectl logs -n searxng -l app=searxng -c tailscale -f
```

**Common causes:**
- Auth key was not created or is invalid
- Network connectivity issues from the pod
- Tailscale API is unreachable (check firewall/egress rules)

### Cannot Access https://searxng

If you can't access the service via Tailscale:

1. **Verify MagicDNS is enabled** in your Tailnet:
   - Visit: https://login.tailscale.com/admin/dns
   - Ensure MagicDNS is enabled

2. **Check Tailscale Serve configuration**:
   ```bash
   # View Tailscale logs for serve setup
   kubectl logs -n searxng -l app=searxng -c tailscale | grep -i serve
   ```

3. **Test direct access to SearXNG container**:
   ```bash
   # Port-forward to test SearXNG is working
   kubectl port-forward -n searxng svc/searxng-service 8080:8080
   # Then visit http://localhost:8080
   ```

4. **Verify Tailscale Serve is active**:
   - The Tailscale container should show logs about serving HTTPS on port 443
   - Check for errors related to `TS_SERVE_CONFIG`

### Pod Won't Schedule

If the pod remains in `Pending` state:

```bash
kubectl describe pod -n searxng <pod-name>
```

**Common issues:**
- Node `rasp-pi-03` is not available
- Insufficient resources on the node (check with `kubectl top node rasp-pi-03`)
- Node doesn't have the expected hostname label

### Out of Memory (OOM) Issues

If the pod is killed due to OOM:

```bash
kubectl describe pod -n searxng <pod-name>
```

Look for `OOMKilled` status. The combined 550Mi limit should be sufficient for normal operation.

**To check resource usage:**
```bash
kubectl top pod -n searxng
```

### ARM64 Compatibility

Both images support ARM64:
- `searxng/searxng:latest` - multi-arch
- `tailscale/tailscale:latest` - multi-arch

## Configuration

The ConfigMap contains basic SearXNG settings. To customize:

1. Edit the `settings.yml` in the ConfigMap
2. Apply the changes: `kubectl apply -f deployment.yaml`
3. Restart the deployment: `kubectl rollout restart deployment/searxng -n searxng`

## Security Considerations

**Tailscale Integration Benefits:**
- ✅ **Zero-trust networking**: Only accessible via your Tailnet (no public exposure)
- ✅ **Automatic HTTPS**: TLS certificates managed by Tailscale
- ✅ **Identity-based access**: Leverage Tailscale ACLs for fine-grained control
- ✅ **MagicDNS**: No DNS configuration or port forwarding required

**Application Security:**
- ✅ Secret keys stored in Kubernetes Secrets (not hardcoded)
- ✅ Dedicated namespace isolation
- ✅ Resource limits prevent resource exhaustion
- ✅ ConfigMap mounted read-only
- ✅ Tailscale sidecar runs in userspace mode (no NET_ADMIN capability)
- ✅ Non-root execution for Tailscale sidecar

**Recommended ACL Configuration:**

Add to your Tailscale ACL policy:

```json
{
  "tagOwners": {
    "tag:k8s": ["you@example.com"],
    "tag:searxng": ["you@example.com"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["autogroup:member"],
      "dst": ["tag:searxng:443"]
    }
  ]
}
```

This allows all Tailnet members to access SearXNG on port 443.

## Maintenance

### Update SearXNG

```bash
# Update the SearXNG image
kubectl set image deployment/searxng searxng=searxng/searxng:latest -n searxng

# Or trigger a complete rollout
kubectl rollout restart deployment/searxng -n searxng
```

### Update Tailscale Sidecar

```bash
# Update the Tailscale sidecar image
kubectl set image deployment/searxng tailscale=tailscale/tailscale:latest -n searxng

# Or trigger a complete rollout
kubectl rollout restart deployment/searxng -n searxng
```

### Rotate Tailscale Auth Key

If your auth key expires or needs rotation:

```bash
# Generate a new auth key in Tailscale admin console
# Then update the secret
kubectl delete secret searxng-tailscale-auth -n searxng
kubectl create secret generic searxng-tailscale-auth \
  --from-literal=authkey=tskey-auth-NEW-KEY \
  -n searxng

# Restart the deployment to use the new key
kubectl rollout restart deployment/searxng -n searxng
```

**Note**: With a reusable auth key, rotation is only needed when the key expires (90+ days).

### View Resource Usage

```bash
# View pod resource usage
kubectl top pod -n searxng

# View per-container resource usage
kubectl top pod -n searxng --containers
```

### Backup Tailscale State

The Tailscale state is persisted in a PVC. To backup:

```bash
# Get the PV backing the PVC
kubectl get pvc searxng-tailscale-state -n searxng

# Backup depends on your storage class (local-path, NFS, etc.)
# For local-path, state is stored on the node at:
# /var/lib/rancher/k3s/storage/<pvc-volume-name>
```

## Architecture Diagrams

### Network Flow

```
┌─────────────────────────────────────────────────────────┐
│                    Tailscale Network                     │
│                                                          │
│  ┌──────────┐    HTTPS:443      ┌──────────────────┐   │
│  │   User   │ ──────────────────>│  searxng node    │   │
│  │  Device  │                    │  (MagicDNS)      │   │
│  └──────────┘                    └──────────────────┘   │
│                                            │             │
└────────────────────────────────────────────┼─────────────┘
                                             │
                                             ▼
                              ┌──────────────────────────┐
                              │  Kubernetes Pod          │
                              │  (rasp-pi-03)           │
                              │                          │
                              │  ┌────────────────────┐  │
                              │  │ Tailscale Sidecar │  │
                              │  │ (HTTPS -> HTTP)   │  │
                              │  │ Port: 443 -> 8080 │  │
                              │  └─────────┬──────────┘  │
                              │            │ localhost   │
                              │            ▼             │
                              │  ┌────────────────────┐  │
                              │  │  SearXNG Container│  │
                              │  │  Port: 8080       │  │
                              │  └────────────────────┘  │
                              │                          │
                              └──────────────────────────┘
```

## References

- [SearXNG Documentation](https://docs.searxng.org/)
- [SearXNG Docker Hub](https://hub.docker.com/r/searxng/searxng)
- [SearXNG GitHub](https://github.com/searxng/searxng)
- [Tailscale Serve Documentation](https://tailscale.com/kb/1242/tailscale-serve/)
- [Tailscale Kubernetes Guide](https://tailscale.com/kb/1185/kubernetes/)
- [Tailscale Sidecar Pattern](https://tailscale.com/kb/1282/kubernetes-sidecar/)
