# PriorityClasses — tenant workload tiering

Two cluster-scoped `PriorityClass` resources used by tenant workloads on
this homelab. Both sit safely below the Kubernetes `system-*` classes so
they can't starve the control plane.

| Class | Value | Use for | QoS pairing |
|---|---|---|---|
| `hl-tenant-critical` | 1000 | Latency-sensitive, user-facing services | `requests == limits` → Guaranteed |
| `hl-tenant-background` | 100 | Batch jobs, sync/index/cleanup workloads | `requests << limits` → Burstable |

## How kubelet uses these

When the node hits memory pressure (soft eviction threshold), kubelet
orders pods for eviction by:

1. QoS class — **BestEffort** evicted first, then **Burstable**, then **Guaranteed**.
2. Within the same QoS, **lower PriorityClass value** evicted first.
3. Within the same QoS+priority, larger memory consumers go first.

So a Guaranteed pod with `hl-tenant-critical` is essentially never evicted
unless a system-* pod needs the room.

## How the scheduler uses these

If a node is full and a `hl-tenant-critical` pod is unschedulable, the
scheduler will **preempt** lower-priority pods (e.g. `hl-tenant-background`)
to make room. `preemptionPolicy: PreemptLowerPriority` is explicit on both
classes so this behavior is always enforced.

## Applying to a workload

```yaml
spec:
  priorityClassName: hl-tenant-critical   # or hl-tenant-background
  containers:
    - name: app
      resources:
        # For Guaranteed: requests must equal limits, set on both CPU and memory.
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 500m
          memory: 1Gi
```

For background workloads, keep `requests` small and `limits` generous —
the pod sits in QoS Burstable and is fair game when the node tightens.

## Why this exists

A control-plane node sustaining transient peaks of memory or CPU during
end-user activity needs a way to tell the scheduler/kubelet which pods are
load-bearing for that activity and which are background. Without explicit
classes, every pod sits at priority 0 and the kubelet's tiebreakers
(largest memory consumer first) are the only signal — which is the
opposite of what you want when streaming.
