# Runbook: RPi OOM Mitigation

| Field | Value |
|:--- |:--- |
| **Severity** | 🟡 Warning (degraded) · 🔴 Critical if control-plane-adjacent |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-05-12 |
| **Owner** | @ariel-extending851 |

Raspberry Pi nodes — particularly the **1 GB RPi 3** — sit at a hard memory ceiling. A workload that drifts onto this node, or grows past its declared limit on the 8 GB RPi 4, will trigger the kernel OOM killer and produce a cascade: kubelet evicts pods, the kernel kills processes, and (in the worst case) `tailscaled` or `kubelet` itself dies and the node disappears from the cluster.

This runbook treats memory pressure as a **scheduling problem**, not a memory-tuning problem. The fix is to push workloads off the constrained node, not to make the constrained node carry more.

> Related symptom path: if the cluster API is already unreachable, run [`control-plane-recovery.md`](control-plane-recovery.md) first; the OOM-killing cascade is one of its root causes.

---

## 1. Symptoms

You're hitting this if one or more of:

- Prometheus alert `NodeMemoryHigh` for `node=rasp-pi-03` or `rasp-pi-04`
- `kubectl describe node <rpi>` shows `MemoryPressure: True`
- `dmesg -T | grep -i 'killed process'` recent entries
- Pods on the node intermittently `OOMKilled` (`kubectl get events -A | grep OOMKilled`)
- `kubectl top node` shows the RPi 3 at >85 % memory for >5 min

---

## 2. Triage

```bash
# 2.1 Identify the offender
kubectl top pod --all-namespaces --sort-by=memory | head -20

# 2.2 Confirm the affected node
NODE=rasp-pi-03
kubectl describe node "$NODE" | grep -E '(MemoryPressure|Allocated|Capacity|memory:)'

# 2.3 List what's scheduled there and why
kubectl get pod -A -o wide --field-selector spec.nodeName="$NODE"

# 2.4 Inspect recent OOM events on the node (requires SSM or tailnet SSH)
ssh "$NODE.tail57bf10.ts.net" "dmesg -T | grep -i 'killed process' | tail -20"
```

The RPi 3's authorized workload set is **Tailscale subnet router + node-exporter + AdGuard (host-network DNS)**. Anything else found on it is drift and must be re-pinned.

---

## 3. Mitigation Tiers

Apply in order. Each tier is a permanent fix committed to git, not a `kubectl edit`. If a workaround must hold the line until the PR merges, log it in the incident timeline.

### 3.1 Tier 1 — Re-pin the offender (correct scheduling)

The offender drifted onto the RPi 3 because the manifest lacks (or has a too-broad) `nodeSelector`. The fix is to pin the workload to the appropriate tier.

```yaml
# Pattern for "RPi 4 only" (storage / media / observability proxy tier)
spec:
  template:
    spec:
      nodeSelector:
        node.kubernetes.io/instance-type: raspberry-pi-4
      tolerations: []
```

```yaml
# Pattern for "AWS only" (stateless, burstable)
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: node.kubernetes.io/instance-type
                    operator: In
                    values: [t3.small, t3.medium]
```

Commit the change in `k8s/apps/<offender>/deployment.yaml` (or the relevant overlay). ArgoCD will reconcile within one sync cycle.

### 3.2 Tier 2 — Tighten kubelet eviction on the RPi 3

If the RPi 3 is hosting only its authorized workloads but the eviction threshold is too loose, raise it so the kubelet evicts earlier (less destructive than waiting for the kernel OOM killer).

```yaml
# ansible/roles/rpi_optimization/defaults/main.yml — affects RPi 3 only via host_vars
rpi_kubelet_eviction_hard_memory_available: "150Mi"   # default is too generous for 1 GB
rpi_kubelet_eviction_soft_memory_available: "300Mi"
rpi_kubelet_eviction_soft_grace_period_memory_available: "1m30s"
```

Apply via `make ansible-deploy --tags rpi_optimization`. Verify:

```bash
ssh rasp-pi-03.tail57bf10.ts.net "cat /var/lib/rancher/k3s/agent/etc/kubelet.conf | grep -A4 evictionHard"
```

### 3.3 Tier 3 — Repel taint (last-resort, used sparingly)

If a workload keeps drifting back despite §3.1, add a taint to the RPi 3 so only explicitly-tolerating pods can land there.

```bash
kubectl taint node rasp-pi-03 hl.io/edge-only=true:NoSchedule
```

The authorized workloads (Tailscale subnet router, node-exporter, AdGuard) need:

```yaml
tolerations:
  - key: hl.io/edge-only
    operator: Equal
    value: "true"
    effect: NoSchedule
```

Like all manual operations, the taint must be promoted to the Ansible inventory (`host_vars/rasp-pi-03.yml`) within the same PR; otherwise the next `make ansible-deploy` will reverse it.

---

## 4. What NOT To Do

!!! danger "Anti-patterns that worsen the problem"
    - **Do not enable swap on the RPi 3.** Kubernetes refuses to start with swap enabled by default; Longhorn explicitly forbids it. The "performance" you would buy is illusory under sustained memory pressure — disk I/O collapses long before the OOM killer fires.
    - **Do not raise the pod's `resources.limits.memory` past the node's capacity ceiling.** Limits are not a workload budget; they are a guarantee to the kernel. A 700 Mi limit on a 1 GB node means *one* such pod can starve the kubelet.
    - **Do not delete the pod and hope the next scheduling lands somewhere else.** StatefulSets are sticky; ReplicaSets reschedule under the same constraints. The next pod lands in the same place unless the manifest changes.
    - **Do not silence the alert without a remediation PR.** A silenced alert with no underlying change is a regression waiting to happen — see [`../security/audit-history.md`](../security/audit-history.md) for the policy on time-boxed silences.

---

## 5. Verification

After applying the mitigation:

```bash
# 5.1 Pod is no longer on the RPi 3
kubectl get pod -A -o wide | grep "$OFFENDER"

# 5.2 Node memory is stable
kubectl top node rasp-pi-03

# 5.3 No new OOMKilled events for 30 min
kubectl get events -A --sort-by='.lastTimestamp' \
  | grep -i 'OOMKilled\|Evicted' \
  | awk -v t="$(date -d '30 minutes ago' --iso-8601=seconds)" '$1 >= t'

# 5.4 MemoryPressure is False
kubectl describe node rasp-pi-03 | grep MemoryPressure
```

Pass criteria: `MemoryPressure: False`, no new evictions in the last 30 min, `MemoryAvailable > 200 Mi` on the RPi 3.

---

## 6. Prevention

If the same workload keeps drifting onto the RPi 3:

1. The manifest's `nodeSelector` is too permissive. Tighten it (§3.1) and back the fix with a Conftest rule under [`k8s/policies/`](../../k8s/policies/) that fails the PR if a Deployment lacks an explicit `nodeSelector`.
2. Add a matching Kyverno `ClusterPolicy` so the same invariant is enforced at admission. See [`../security/runtime-enforcement.md#22-mode-promotion-procedure`](../security/runtime-enforcement.md#21-mode-promotion-procedure).
3. Reflect the authorized-workload set for the RPi 3 in [`../operations/resource-limits.md`](../operations/resource-limits.md) so a future operator does not re-introduce the drift.

---

## 7. Related

- **Control plane recovery (when the API is unreachable):** [`control-plane-recovery.md`](control-plane-recovery.md)
- **Resource limits and the cluster's memory budget:** [`../operations/resource-limits.md`](../operations/resource-limits.md)
- **Node-allocation rationale:** [`../architecture/overview.md#2-resource-allocation-rationale`](../architecture/overview.md#2-resource-allocation-rationale)
- **Runtime enforcement (Kyverno require-resource-limits policy):** [`../security/runtime-enforcement.md`](../security/runtime-enforcement.md)
- **Disaster recovery (often unblocks stuck restores via OOM relief):** [`disaster-recovery-velero.md`](disaster-recovery-velero.md)
