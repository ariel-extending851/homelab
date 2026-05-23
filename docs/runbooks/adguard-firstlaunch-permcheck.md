# AdGuard Home — first-launch permcheck CrashLoop

> **Severity:** 🟡 Warning (single-app DNS outage; no cluster impact)
> **Last tested:** 2026-05-09
> **Owner:** @ariel-extending851

## Symptom

Pod `adguard/adguardhome-*` CrashLoopBackOff with rapidly climbing restart count. `kubectl logs -n adguard -l app=adguardhome` shows the same four lines on every restart, exiting within the same second:

```text
[info] starting adguard home version="AdGuard Home, version v0.107.74"
[info] this is the first time adguard home has been launched
[info] checking if adguard home has the necessary permissions
[error] this is the first launch of adguard home; you must run it as administrator.
```

Trigger: any deploy that lands a fresh PVC (no prior `AdGuardHome.yaml` in `/opt/adguardhome/conf`) AND runs the container as a non-root UID. Once the persistent volume contains a valid config from a previous successful launch, AdGuard skips the permcheck and the same Pod spec runs cleanly — which is why the failure mode is invisible until a re-provision (cluster rebuild, PVC drop, namespace teardown).

## Root cause

AdGuard Home v0.107.50+ (`internal/permcheck/permcheck_linux.go`) gates its first launch behind a permission check that:

1. Returns early if `unix.Geteuid() == 0` (running as root).
2. Otherwise inspects the **file capabilities** on the binary itself via `cap.GetFile("/opt/adguardhome/AdGuardHome")` — looking for `CAP_NET_BIND_SERVICE` and `CAP_NET_RAW`.

The upstream image `adguard/adguardhome` ships **without** `setcap` applied to the binary, so a non-root container fails step 2 even when the Pod has `securityContext.capabilities.add: [NET_BIND_SERVICE, NET_RAW]`. Pod-level capability injection adds caps to the **process** (Permitted/Effective sets), not as **file caps** on the executable.

This is upstream-by-design — the permcheck deliberately reads file caps because it was added to handle bare-metal installs where someone untar'd the binary as a non-root user. Container caps were not considered.

## Fix (applied 2026-05-09)

`k8s/apps/adguard/deployment.yaml` — Pod-level `securityContext`:

```yaml
# Before
runAsUser: 65534
runAsGroup: 65534
fsGroup: 65534

# After
runAsUser: 0
runAsGroup: 0
# fsGroup dropped — root owns mounts by default
```

Container `securityContext.capabilities.add` gains `NET_RAW` (consulted by the permcheck alongside `NET_BIND_SERVICE`):

```yaml
capabilities:
  add:
    - NET_BIND_SERVICE
    - NET_RAW
    - SETUID
    - SETGID
  drop:
    - ALL
```

Mitigations retained:
- `privileged: false`
- `allowPrivilegeEscalation: false` (sets `no_new_privs` on the process; no setuid binary in PATH can escalate)
- `capabilities.drop: [ALL]` then explicit add — same minimal set as before plus `NET_RAW`
- `hostNetwork: true` is a hard requirement for binding host port 53 (LAN DNS)
- Single-namespace, single-pod scope
- NetworkPolicy `default-deny` + `allow-adguardhome` egress allowlist still in effect

## Verify the fix

```bash
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml

kubectl -n adguard rollout restart deploy/adguardhome
kubectl -n adguard rollout status deploy/adguardhome --timeout=120s
kubectl -n adguard logs -l app=adguardhome --tail=30
# Expect: "AdGuard Home is available at the following addresses" + bind on :3000

AGENT_IP=$(kubectl get node k3s-agent -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
curl -s -o /dev/null -w "%{http_code}\n" http://${AGENT_IP}:3000/
# Expect: 200 or 302
```

## If the fix does not stick

If the deploy.strategy `Recreate` doesn't pick up the new Pod template (rare):

```bash
kubectl -n adguard delete pod -l app=adguardhome
```

If the same `must run it as administrator` log persists after `runAsUser: 0` — that would be a regression upstream. Open an issue at <https://github.com/AdguardTeam/AdGuardHome/issues> and apply the workaround:

```yaml
# Add to deployment.spec.template.spec
initContainers:
  - name: setcap
    image: alpine:3.20
    command:
      - sh
      - -c
      - |
        apk add --no-cache libcap
        setcap cap_net_bind_service,cap_net_raw+ep /opt/adguardhome/AdGuardHome
    volumeMounts:
      - name: adguard-binary
        mountPath: /opt/adguardhome
    securityContext:
      runAsUser: 0
```

(Requires switching `/opt/adguardhome` to a shared `emptyDir` and copying the binary in — non-trivial. Defer unless permcheck breaks again upstream.)

## Cleanups landed in the same PR

- `k8s/apps/adguard/pv.yaml` deleted. The static PV declared `storageClassName: local-storage-adguard` while the PVC requested `local-path` — they would never bind. The file also pinned to node `k3s-agent-2`, which has not existed in the cluster since the 2026-05-04 prod re-deploy. Dynamic `rancher.io/local-path` provisioning has covered this PVC since first deploy.

## Hardening deferred (separate PRs)

- Add `nodeSelector: role=dns-server` so the DNS bind IP is stable across reschedules. Today the pod lands on whichever node the scheduler picks; clients have to track the IP.
- Reintroduce a static PV with the correct `storageClassName: local-path` and a node that exists, plus matching `nodeSelector` on the deployment.
- Init container `setcap` approach to drop back to non-root once upstream stabilizes.
