# SearXNG Deployment for Raspberry Pi 3

This directory contains Kubernetes manifests for deploying SearXNG, a privacy-respecting metasearch engine, on the Raspberry Pi 3 node (rasp-pi-03).

## Overview

SearXNG is configured with strict resource constraints to accommodate the limited RAM (~800MB free) available on the Raspberry Pi 3.

## Components

- **Namespace**: `searxng`
- **Secret**: Stores the SearXNG secret key (must be configured before deployment)
- **ConfigMap**: SearXNG configuration settings
- **Deployment**: SearXNG application with resource limits and health probes
- **Service**: ClusterIP service exposing port 8080
- **Ingress**: Traefik ingress for external access via `searxng.local`

## Resource Limits

The deployment uses strict resource limits suitable for Raspberry Pi 3:

- **Memory Request**: 150Mi (conservative baseline)
- **Memory Limit**: 400Mi (strict cap to prevent OOM issues and leave room for OS)
- **CPU Request**: 100m (minimal CPU reservation)
- **CPU Limit**: 500m (allows bursts but prevents monopolization)

## Prerequisites

1. K3s cluster must be running
2. Node `rasp-pi-03` must be available with label `kubernetes.io/hostname: rasp-pi-03`
3. Traefik ingress controller must be installed (comes with K3s by default)

## Deployment Instructions

### 1. Generate a Secure Secret Key

Before deploying, you must generate a secure random secret key:

```bash
# Generate and create the secret
kubectl create secret generic searxng-secret \
  --from-literal=secret-key=$(openssl rand -hex 32) \
  -n searxng --dry-run=client -o yaml | kubectl apply -f -
```

Or manually edit the Secret in `deployment.yaml` and replace the placeholder:

```yaml
stringData:
  secret-key: "YOUR-SECURE-RANDOM-KEY-HERE"
```

### 2. Apply the Manifests

```bash
kubectl apply -f deployment.yaml
```

### 3. Verify Deployment

```bash
# Check pod status
kubectl get pods -n searxng

# Check if pod is running on rasp-pi-03
kubectl get pods -n searxng -o wide

# View logs
kubectl logs -n searxng -l app=searxng

# Check service
kubectl get svc -n searxng
```

### 4. Access SearXNG

Add an entry to your `/etc/hosts` file pointing to one of your cluster nodes:

```
<node-ip> searxng.local
```

Then access SearXNG at: `http://searxng.local`

## Monitoring

The deployment includes health probes:

- **Liveness Probe**: HTTP GET on `/` every 30s (prevents zombie processes)
- **Readiness Probe**: HTTP GET on `/` every 10s (ensures pod readiness)

## Troubleshooting

### Pod Won't Schedule

If the pod remains in `Pending` state, check:

```bash
kubectl describe pod -n searxng <pod-name>
```

Common issues:
- Node `rasp-pi-03` is not available
- Insufficient resources on the node
- Node doesn't have the expected hostname label

### Out of Memory (OOM) Issues

If the pod is killed due to OOM:

```bash
kubectl describe pod -n searxng <pod-name>
```

Look for `OOMKilled` status. The 400Mi limit should be sufficient for normal operation, but you may need to adjust based on actual usage.

### ARM64 Compatibility

The deployment uses `searxng/searxng:latest` which is a multi-arch image supporting ARM64. If you experience issues, you can explicitly use:

```yaml
image: searxng/searxng:latest
```

The Docker Hub image supports multiple architectures including `linux/arm64`.

## Configuration

The ConfigMap contains basic SearXNG settings. To customize:

1. Edit the `settings.yml` in the ConfigMap
2. Apply the changes: `kubectl apply -f deployment.yaml`
3. Restart the deployment: `kubectl rollout restart deployment/searxng -n searxng`

## Security Considerations

- The secret key is stored in a Kubernetes Secret (not hardcoded)
- The deployment runs in a dedicated namespace
- Resource limits prevent resource exhaustion
- ConfigMap is mounted read-only

## Maintenance

### Update SearXNG

```bash
# Update the image
kubectl set image deployment/searxng searxng=searxng/searxng:latest -n searxng

# Or trigger a rollout to pull the latest image
kubectl rollout restart deployment/searxng -n searxng
```

### View Resource Usage

```bash
kubectl top pod -n searxng
```

## References

- [SearXNG Documentation](https://docs.searxng.org/)
- [SearXNG Docker Hub](https://hub.docker.com/r/searxng/searxng)
- [SearXNG GitHub](https://github.com/searxng/searxng)
