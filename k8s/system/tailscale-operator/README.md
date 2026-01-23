# Tailscale Kubernetes Operator

This directory documents the Tailscale Kubernetes Operator deployment.

**NOTE:** The operator is deployed via **Helm**, not static manifests.

## Installation

The operator was installed using the official Helm chart:

```bash
helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update

# Install/Upgrade
helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --namespace=tailscale \
  --create-namespace \
  --set-string oauth.clientId=<YOUR_CLIENT_ID> \
  --set-string oauth.clientSecret=<YOUR_CLIENT_SECRET> \
  --set operatorConfig.defaultTags="tag:k8s-operator" \
  --set proxyConfig.defaultTags="tag:k8s-operator" \
  --wait
```

## Configuration

- **Namespace:** `tailscale`
- **OAuth Tags:** Configured to use `tag:k8s-operator` (matching your existing ACLs).
- **Proxy Tags:** Proxies created by the operator will also use `tag:k8s-operator`.

## Upgrade

To upgrade the operator version:

```bash
helm repo update
helm upgrade tailscale-operator tailscale/tailscale-operator \
  --namespace=tailscale \
  --set-string oauth.clientId=<YOUR_CLIENT_ID> \
  --set-string oauth.clientSecret=<YOUR_CLIENT_SECRET> \
  --set operatorConfig.defaultTags="tag:k8s-operator" \
  --set proxyConfig.defaultTags="tag:k8s-operator"
```

## Uninstall

```bash
helm uninstall tailscale-operator -n tailscale
```
