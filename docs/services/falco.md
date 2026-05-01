# Falco

> **Status:** Active · **Namespace:** `falco` · **Last reviewed:** 2026-05-01
> **Manifests:** [`k8s/apps/falco/`](../../k8s/apps/falco/) · **Image:** `falcosecurity/falco:0.43.1`

Runtime security DaemonSet running modern eBPF probes. Detects suspicious syscalls (shell-in-container, sensitive-file reads, package-manager invocations, privilege escalation) and emits structured JSON events to stdout, where the OTEL collector picks them up and ships them to Loki.

## Topology

| Item | Value |
|---|---|
| Type | DaemonSet (one pod per eligible node) |
| Eligible nodes | All except `rasp-pi-03` (excluded via `nodeAffinity`) |
| Engine | `modern_ebpf` (no kernel module / no driver build) |
| `hostNetwork` / `hostPID` | `true` (required to read host syscalls + namespaces) |
| Privileged | `false` — runs with explicit `CAP_BPF`, `CAP_PERFMON`, `CAP_SYS_PTRACE`, `CAP_SYS_RESOURCE`, `CAP_SYS_ADMIN`, `CAP_DAC_READ_SEARCH`, `CAP_SYS_CHROOT` |
| Priority | `system-node-critical` |

`rasp-pi-03` exclusion: 1 GB RAM Pi3 cannot accommodate Falco's 100–200 Mi steady plus syscall-storm bursts above the 512 Mi eviction-soft floor. Encoded in [`daemonset.yaml`](../../k8s/apps/falco/daemonset.yaml) as a hard nodeAffinity rule.

## Configuration ([`configmap.yaml`](../../k8s/apps/falco/configmap.yaml))

| Setting | Value | Why |
|---|---|---|
| `engine.kind` | `modern_ebpf` | No kernel module dependency |
| `json_output` | `true` | Structured logs → OTEL → Loki → Grafana |
| `priority` | `notice` | Drops `info`/`debug` to keep volume sane |
| `syscall_event_drops.threshold` | `0.1` | Tolerates short syscall storms before alerting |
| `buffered_outputs` | `false` | Real-time emission |

Rule files: `/etc/falco/falco_rules.yaml` (upstream defaults) + `/etc/falco/falco_rules.local.yaml` (cluster-specific overrides — keep additions reviewable).

## Operations

```bash
# Pod health
kubectl get ds falco -n falco
kubectl logs -n falco -l app=falco --tail=50

# Search for events in Loki/Grafana
# {namespace="falco"} | json | priority="notice"

# Tail syscall drops (means buffers undersized for the node)
kubectl logs -n falco -l app=falco | grep -i "syscall_event_drops"
```

## Tuning

- **High false-positive on a workload:** add an exception in `falco_rules.local.yaml` instead of disabling a rule. Keep the exception scoped (image, container name, k8s.ns.name).
- **Memory pressure on RPi:** raise the `cpus_for_each_buffer` (currently `2`) to reduce ring-buffer count. Test on `rasp-pi-04` first.

## Limitations

- `rasp-pi-03` has no runtime visibility (intentional). Workloads pinned there (AdGuard) rely on AppArmor + read-only rootfs alone.
- Modern eBPF requires kernel ≥5.8 with `CONFIG_BPF_KPROBE_OVERRIDE`. AWS k3s nodes (Ubuntu 22.04) and `rasp-pi-04` (Ubuntu 22.04 ARM64) both meet this — verified during Ansible bootstrap.

## Related

- [`cilium.md`](cilium.md) — companion eBPF stack (network observability)
- [`../security/overview.md`](../security/overview.md) — overall threat model
- [`../runbooks/trivy-exceptions.md`](../runbooks/trivy-exceptions.md) — image-scan exception process (similar tuning workflow)
