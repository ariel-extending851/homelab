# Cilium

> **Status:** Active · **Namespace:** `kube-system` (CNI add-on) · **Last reviewed:** 2026-05-01
> **Manifests:** [`k8s/apps/cilium/`](../../k8s/apps/cilium/) · **Helm chart:** `cilium/cilium 1.19.3`

eBPF data plane installed *alongside* Flannel for observability and policy hooks. Flannel remains the primary CNI; Cilium runs in **tunnel (VXLAN) mode** with `kubeProxyReplacement: false` and `encryption: false` so it does not double-encrypt over Tailscale's WireGuard mesh.

## Why Cilium here

- Hybrid x86/ARM64 cluster with the workload already encrypted by Tailscale node-to-node — Cilium is used for eBPF visibility, not as a replacement CNI.
- L7/Hubble are **disabled** in the deployed values to keep memory low on the RPi nodes (`hubble.*: false`, `l7Proxy: false`, `bandwidthManager: false`).
- The Cilium operator is pinned off `rasp-pi-3` via `nodeAffinity` (`raspberry-pi-3` excluded — 1 GB RAM is too tight).

## Key configuration ([`application.yaml`](../../k8s/apps/cilium/application.yaml))

| Setting | Value | Why |
|---|---|---|
| `routingMode` | `tunnel` | Avoids per-node BGP/router config |
| `tunnelProtocol` | `vxlan` | Same as Flannel; no double-tunnel |
| `mtu` | `1280` | Matches Tailscale WireGuard MTU |
| `devices` | `tailscale0` | Bind eBPF to the tailnet interface |
| `encryption.enabled` | `false` | Tailscale already encrypts |
| `kubeProxyReplacement` | `false` | k3s runs kube-proxy; Cilium augments |
| `cni.exclusive` | `true` | Cilium owns CNI chaining order |
| `bpf.masquerade` | `false` | Flannel handles masquerade |

## Operations

```bash
# Pod health (operator + per-node agents)
kubectl get pods -n kube-system -l k8s-app=cilium
kubectl get pods -n kube-system -l name=cilium-operator

# Agent status on a specific node
kubectl exec -n kube-system ds/cilium -- cilium status --brief

# Per-node connectivity check
kubectl exec -n kube-system ds/cilium -- cilium connectivity test --single-node-test
```

## Troubleshooting

**Agent CrashLoopBackOff after k3s upgrade**
- Check kernel BPF support: `kubectl exec -n kube-system ds/cilium -- cilium bpf status`. Agents require kernel ≥5.10 for modern eBPF; the RPi nodes are explicitly verified before rollout.

**Operator unschedulable**
- The operator excludes `raspberry-pi-3` instance-type. If both AWS nodes are stopped (off-hours), the operator stays Pending — expected.

**Network drops after node restart**
- `tailscale0` device must exist before Cilium agent starts. The deploy ordering relies on the Tailscale role (`ansible/roles/tailscale`) running before k3s join. If the device is missing, restart the agent: `kubectl rollout restart ds/cilium -n kube-system`.

## Roadmap

Hubble remains disabled to control RAM. Re-enabling requires a memory-budget review, especially on RPi nodes — track in [`../security/fixes-backlog.md`](../security/fixes-backlog.md) if pursued.

## Related

- [`falco.md`](falco.md) — runtime security (companion eBPF stack)
- [`../architecture/networking.md`](../architecture/networking.md)
- [`../architecture/kubernetes.md`](../architecture/kubernetes.md)
