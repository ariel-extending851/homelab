# Runbook: Critical Control Plane Unresponsive

| | |
| :--- | :--- |
| **Severity** | 🔴 CRITICAL |
| **Status** | ✅ Reviewed |
| **Last Tested**| 2026-02-17 |
| **Owner** | Senior Tech Lead |

---

## 1. Symptoms

You know you have this problem if you experience one or more of the following:
- `kubectl get nodes` command times out or fails to connect to the server.
- ArgoCD UI is inaccessible or shows connection errors.
- Tailscale ingresses for your services (e.g., Grafana, ***) are not responding.
- Pods are stuck in a `CrashLoopBackOff` or `OOMKilled` state on a resource-constrained node (like a Raspberry Pi).

## 2. Root Cause Analysis

This issue typically occurs when a resource-constrained node (e.g., a Raspberry Pi with limited RAM) becomes overloaded by too many pods. This can trigger a cascading failure:
1.  **Pod Overload:** Pods are scheduled on a node that lacks sufficient CPU or RAM.
2.  **OOMKilled:** The node's kernel starts killing processes (including parts of `k3s`) due to memory pressure.
3.  **Control Plane Failure:** Critical cluster components on the node become unresponsive.
4.  **API Unresponsive:** The Kubernetes API server can no longer be reached, making `kubectl` commands fail.

A common trigger for this is when a `StatefulSet`'s pod is deleted. Due to the "sticky" nature of `StatefulSet` identities, Kubernetes will try to reschedule the pod on the *same node*, leading to a cycle of crashes if that node is overloaded.

## 3. Resolution Steps

The goal is to alleviate pressure on the overloaded node so the cluster can recover. We will do this by **deleting the parent `StatefulSet`**, which breaks the sticky scheduling and allows ArgoCD to recreate it on a healthy node.

> [!WARNING]
> This procedure will cause a brief (1-3 minute) downtime for the affected services while they are recreated.

---

### Step 1: Identify the Failing Pod and its Parent StatefulSet

First, identify which pods are causing the issue. Even if `kubectl` is slow, you can often get a list of pods.

```bash
# This command might be slow, but should eventually return.
kubectl get pods -A -o wide | grep -E "CrashLoopBackOff|OOMKilled|Pending"
```

**Expected Output:**
You will see pods on the overloaded node (e.g., `rasp-pi-03`) that are failing. Note the pod name, like `ts-***-ingress-0`. The parent `StatefulSet` is the pod name without the `-0` suffix (e.g., `ts-***-ingress`).

### Step 2: Delete the Parent StatefulSet

Delete the `StatefulSet` (not the pod). This will trigger ArgoCD and the Tailscale Operator to recreate it correctly on a node with available resources.

```bash
# Replace <statefulset-name> with the name from the previous step.
# Example: kubectl delete statefulset ts-***-ingress -n tailscale
STATEFULSET_NAME="<statefulset-name>"
NAMESPACE="tailscale"

echo "Deleting StatefulSet ${STATEFULSET_NAME} in namespace ${NAMESPACE}..."
kubectl delete statefulset "${STATEFULSET_NAME}" -n "${NAMESPACE}" --ignore-not-found=true
```

### Step 3: Trigger an ArgoCD Refresh (Optional)

ArgoCD should detect the change automatically, but you can trigger a manual refresh to speed up the process.

```bash
# This tells ArgoCD to immediately check the Git repository for changes.
kubectl patch application homelab-apps-root -n argocd --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'
```

---

## 4. Verification Steps

After performing the resolution, verify that the system has recovered.

### Step 1: Wait for Pod Recreation

Wait for 1-2 minutes for the new pod to be scheduled and start.

```bash
# Watch for the new pod to be created and enter the 'Running' state.
# The new pod should appear on a healthy node (e.g., k3s-agent-2 or rasp-pi-04).
kubectl get pods -n tailscale -o wide -w
```

### Step 2: Verify Node Status

The Kubernetes API should now be responsive.

```bash
# All nodes should report as 'Ready'.
kubectl get nodes -o wide
```
**Expected Output:**
You should see all your nodes (`k3s-server`, `k3s-agent`, etc.) in the `Ready` state.

### Step 3: Test Service Endpoint

Verify that the application's Tailscale ingress is now accessible.

```bash
# Replace with the URL of the service you were fixing.
# Example: curl -s -o /dev/null -w "%{http_code}" https://***.tail57bf10.ts.net
SERVICE_URL="<your-service-url>"

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}")

if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "302" ]; then
    echo "✅ SUCCESS: Service is accessible (HTTP $HTTP_STATUS)"
else
    echo "❌ FAILURE: Service returned HTTP $HTTP_STATUS"
fi
```

---

## 5. Rollback Procedure

Since this procedure involves deletion and automatic recreation, a "rollback" means reverting to the original problematic state, which is not desirable.

If the new pod fails to schedule on a healthy node and gets stuck on the overloaded node again, the problem is likely with the application's scheduling rules in the Git repository (`nodeAffinity`, `nodeSelector`). In this case, the **permanent fix is to modify the YAML manifests in Git**, not to perform a manual rollback.
