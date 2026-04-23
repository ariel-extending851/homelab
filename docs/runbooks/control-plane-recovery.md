# Runbook: Control Plane Unresponsive

| Field | Value |
|:--- |:--- |
| **Severity** | 🔴 Critical |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-02-17 |
| **Owner** | @ariel-extending851 |

---

## Symptoms

You're hitting this if you see one or more of:

- `kubectl get nodes` times out or refuses connection
- ArgoCD UI inaccessible or showing connection errors
- Tailscale ingresses for app services (Grafana, ***, etc.) not responding
- Pods stuck in `CrashLoopBackOff` or `OOMKilled` on a resource-constrained node (typically a Raspberry Pi)

## Root Cause

Almost always: a resource-constrained node (Pi with limited RAM) overloaded by too many pods, triggering a cascade:

1. Pod scheduled on node lacking sufficient CPU/RAM
2. Kernel OOM-killer starts murdering processes (including `k3s` itself)
3. Critical cluster components on that node go unresponsive
4. K8s API server becomes unreachable → `kubectl` fails

Common trigger: a `StatefulSet` pod is deleted. Because StatefulSet identities are sticky, K8s reschedules the pod on the **same node**, leading to a crash loop if that node is still overloaded.

## Resolution

**Goal:** alleviate pressure on the overloaded node so the cluster recovers. Method: delete the parent `StatefulSet`, which breaks sticky scheduling and lets ArgoCD recreate the pod on a healthy node.

> ⚠️ This procedure causes **brief downtime (1–3 min)** for the affected services while they are recreated.

### Step 1 — Identify the failing pod and its parent StatefulSet

```bash
# May be slow but should eventually return
kubectl get pods -A -o wide | grep -E "CrashLoopBackOff|OOMKilled|Pending"
```

Look for pods on the overloaded node (e.g., `rasp-pi-03`) that are failing. Note the pod name like `ts-***-ingress-0`. The parent StatefulSet is the name without the `-0` suffix (`ts-***-ingress`).

### Step 2 — Delete the parent StatefulSet

```bash
STATEFULSET_NAME="<from-step-1>"
NAMESPACE="tailscale"     # or the relevant namespace

kubectl delete statefulset "$STATEFULSET_NAME" -n "$NAMESPACE" --ignore-not-found=true
```

ArgoCD + the Tailscale operator will recreate it correctly on a node with available resources.

### Step 3 — (Optional) Trigger ArgoCD refresh

```bash
kubectl patch application homelab-apps-root -n argocd --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'
```

## Verification

### 1. Wait for pod recreation

```bash
# Watch for the new pod (1–2 min)
kubectl get pods -n tailscale -o wide -w
```

The new pod should land on a healthy node (e.g., `k3s-agent-2` or `rasp-pi-04`).

### 2. Confirm node status

```bash
kubectl get nodes -o wide
```

All nodes should report `Ready`.

### 3. Test the affected service endpoint

```bash
SERVICE_URL="https://***.tail57bf10.ts.net"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL")
[ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "302" ] \
  && echo "✅ Service accessible (HTTP $HTTP_STATUS)" \
  || echo "❌ Service returned HTTP $HTTP_STATUS"
```

## Prevention

If the same pod keeps landing on the overloaded node, the application's scheduling rules need fixing in git, not a manual workaround:

- Add `nodeAffinity` excluding the overloaded node, OR
- Add `topologySpreadConstraints` to balance across nodes, OR
- Increase the resource budget on the constrained node (move workload off; or upgrade the Pi)

The fix belongs in the YAML manifests in git, not in `kubectl edit`.

## Rollback

There is no meaningful rollback for this procedure — reverting would mean returning to the broken state. If the new pod fails to schedule on a healthy node, see "Prevention" above and edit the manifest in git.

## Related

- [Tailscale logged out](tailscale-logged-out.md) — different symptom, also causes API unreachability
- [`../architecture/kubernetes.md`](../architecture/kubernetes.md) — node placement model
- [`../operations/resource-limits.md`](../operations/resource-limits.md) — media namespace budget detail
