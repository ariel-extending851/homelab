# Resource Limits

> **Status:** Active
> **Last reviewed:** 2026-01-28 (initial review); migration audit 2026-04-23
> **Owner:** @ariel-extending851

Resource request/limit budget for the **media namespace** on `rasp-pi-04` (Raspberry Pi 4, 4 cores, ~7.6 GB RAM). Other namespaces use Kubernetes defaults.

---

## Current Allocation

| Pod | Container | CPU req | CPU lim | Mem req | Mem lim | Actual CPU | Actual Mem |
|---|---|---:|---:|---:|---:|---:|---:|
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

---

## Recommendation

**Keep current values.** Reasoning:

2. Media apps are bursty — idle ≫ active. Today's allocation gives both:
   - Guaranteed minimum (requests)
   - Burst capacity (limits)
   - Node stability (sum of limits < node capacity)

---

## Monitoring (when to re-evaluate)

```bash
# during active downloads
kubectl top pod -n media --containers

# expected peaks
```

If sustained usage approaches limits, reconsider — likely upgrade to a 16 GB Pi or move workload to AWS.

---

## Optional Optimizations

```yaml
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
  namespace: media
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
  updatePolicy:
    updateMode: "Recreate"   # restarts pods on adjustment
```

VPA isn't installed today. Trade-off: pod restarts on every adjustment, which interrupts active downloads.

---

## GitOps Compliance

Every limit is declared in git, applied through ArgoCD:

The OPA policy [`k8s/policies/resource_limits.rego`](../../k8s/policies/resource_limits.rego) blocks any container from being added without CPU + memory limits — enforced by `make validate-k8s-policies`.

---

## Related

- **K8s policies:** [`../security/network-policies.md`](../security/network-policies.md)
- **Node optimization (Pi-side):** [`../architecture/networking.md#proxy-distribution-across-raspberry-pis`](../architecture/networking.md#proxy-distribution-across-raspberry-pis)
