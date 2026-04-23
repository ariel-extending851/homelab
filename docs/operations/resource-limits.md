# Resource Limits

> **Status:** Active
> **Last reviewed:** 2026-01-28 (initial review); migration audit 2026-04-23
> **Owner:** @ariel-extending851

Resource request/limit budget for the **media namespace** on `rasp-pi-04` (Raspberry Pi 4, 4 cores, ~7.6 GB RAM). Other namespaces use Kubernetes defaults.

---

## Current Allocation

| Pod | Container | CPU req | CPU lim | Mem req | Mem lim | Actual CPU | Actual Mem |
|---|---|---:|---:|---:|---:|---:|---:|
| *** | *** (sidecar) | 20m | 100m | 64Mi | 128Mi | ~5m | ~30Mi |
| *** | *** | 100m | 400m | 256Mi | 512Mi | ~10m | ~102Mi |
| *** | *** | 100m | 500m | 150Mi | 500Mi | 7m | 143Mi |
| *** | *** | 100m | 500m | 150Mi | 500Mi | 6m | 122Mi |
| *** | *** | 100m | 500m | 150Mi | 500Mi | 6m | 146Mi |
| **Totals** | | **420m** | **2100m** | **770Mi** | **2140Mi** | **34m** | **543Mi** |

Node capacity: 4000m CPU / 7988Mi RAM (no system reservations).

---

## Headroom

| Dimension | Requests | Limits | Actual |
|---|---:|---:|---:|
| CPU | 10.5% | 52.5% | 0.85% |
| Memory | 10.1% | 28.1% | 7.1% |

**Verdict:** healthy. Actual usage is well below requests; limits provide ~5× burst capacity for CPU-intensive operations (large library scans, indexer sync, multi-stream downloads).

---

## Observations

- ***** over-provisioned** — actual ~15m CPU / 132Mi memory vs 120m / 320Mi requested (~8× CPU, ~2.4× memory). Snapshot was taken during low-activity period; expect peaks of 400m / 512Mi during multi-download sessions.
- **\*arr stack consistent** — ***, ***, *** have identical resource profiles and similar actual usage. Uniformity is intentional (they share a workload pattern).
- ***** is cheap** — WireGuard userspace adds only ~5m CPU / 30Mi memory per pod, well below its 20m / 64Mi request.

---

## Recommendation

**Keep current values.** Reasoning:

1. RPi 4 has limited RAM; conservative limits prevent OOM kills on a node we share with ***.
2. Media apps are bursty — idle ≫ active. Today's allocation gives both:
   - Guaranteed minimum (requests)
   - Burst capacity (limits)
   - Node stability (sum of limits < node capacity)
3. Total memory limit (2140Mi) leaves ~5848Mi for the kernel, kubelet, Tailscale daemon, ***, and the Tailscale operator proxy pod for ***.tail57bf10.ts.net.

---

## Monitoring (when to re-evaluate)

```bash
# during active downloads
kubectl top pod -n media --containers

# expected peaks
# ***  → up to 400m CPU / 512Mi memory (multiple active downloads)
# ***       → up to 500m / 500Mi (large library scan)
# ***       → same as ***
# ***     → up to 500m / 500Mi (indexer sync + search)
```

If sustained usage approaches limits, reconsider — likely upgrade to a 16 GB Pi or move workload to AWS.

---

## Optional Optimizations

### Reduce *** ceiling (if room is needed for new apps)

```yaml
# k8s/apps/***/deployment.yaml
resources:
  limits:
    cpu: 300m       # was 400m
    memory: 400Mi   # was 512Mi
  requests:
    cpu: 100m
    memory: 256Mi
```

### VPA (vertical pod autoscaler) — future

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: ***-vpa
  namespace: media
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ***
  updatePolicy:
    updateMode: "Recreate"   # restarts pods on adjustment
```

VPA isn't installed today. Trade-off: pod restarts on every adjustment, which interrupts active downloads.

---

## GitOps Compliance

Every limit is declared in git, applied through ArgoCD:

- [`k8s/apps/***/deployment.yaml`](../../k8s/apps/***/deployment.yaml)
- [`k8s/apps/***/deployment.yaml`](../../k8s/apps/***/deployment.yaml)
- [`k8s/apps/***/deployment.yaml`](../../k8s/apps/***/deployment.yaml)
- [`k8s/apps/***/deployment.yaml`](../../k8s/apps/***/deployment.yaml)

The OPA policy [`k8s/policies/resource_limits.rego`](../../k8s/policies/resource_limits.rego) blocks any container from being added without CPU + memory limits — enforced by `make validate-k8s-policies`.

---

## Related

- **Per-service detail:** [`../services/***.md`](../services/***.md), [`../services/***.md`](../services/***.md)
- **K8s policies:** [`../security/network-policies.md`](../security/network-policies.md)
- **Node optimization (Pi-side):** [`../architecture/networking.md#proxy-distribution-across-raspberry-pis`](../architecture/networking.md#proxy-distribution-across-raspberry-pis)
