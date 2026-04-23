# Tailscale Operator

Cluster-wide IngressClass provider for tailnet exposure. Installed via Helm.

For full documentation see **[docs/services/tailscale-operator.md](../../../docs/services/tailscale-operator.md)**.

## Files in this directory

| File | Purpose |
|---|---|
| `values.yaml` | Helm values template (committed, non-secret) |
| `values.sops.yaml` | SOPS-encrypted values overlay (OAuth client ID/secret) |
| `proxy-classes.yaml` | Definitions for `default` and `high-bandwidth` ProxyClass resources |

Install / upgrade: see the full doc.
