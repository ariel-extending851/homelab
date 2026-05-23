# Runbook: Disaster Recovery (Velero)

| Field | Value |
|:--- |:--- |
| **Severity** | 🔴 Critical |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-05-12 |
| **Owner** | @ariel-extending851 |
| **RPO** | 24 h (one nightly backup) |
| **RTO** | ≤ 30 min for a single namespace · ≤ 90 min for a full-cluster restore |

This runbook covers three procedures with increasing blast radius: the **monthly backup verification**, the **quarterly restore drill** into an isolated namespace, and the **full-cluster restore** after catastrophic loss. Run them in that order — the drill validates the assumptions the full restore relies on.

---

## 1. Operational Standard

Velero is deployed as a DaemonSet in the `velero` namespace ([`k8s/apps/velero/`](../../k8s/apps/velero/)). The schedule [`k8s/apps/velero/schedule.yaml`](../../k8s/apps/velero/schedule.yaml):

- Runs daily at **14:00 UTC** (`0 14 * * *`) — chosen to fire after the AWS scheduler boots the cluster at 10:00 BRT and before the 21:00 BRT shutdown.
- Includes the platform namespaces: `adguard`, `argocd`, `golink`, `grafana`, `kube-system`, `loki`, `monitoring`, `otel-collector`, `prometheus`, `tailscale`, `velero`.
- Retention: `336h0m0s` — **14 days**.
- Storage location: `default` (S3 bucket provisioned by [`infra/aws/`](../../infra/aws/), IAM user `velero_backup_user`).
- `snapshotMoveData: false` — metadata-only at the schedule level; PVC data uses the CSI snapshot path when restored.

Bootstrap of the Velero credentials Secret is handled by [`bin/velero_bootstrap_secret.py`](../../bin/velero_bootstrap_secret.py), driven by the Terraform-emitted IAM access key.

!!! abstract "Decision: 24 h RPO, 14 d retention"
    The cluster is a single-operator homelab. Sub-hourly backups would burn S3 dollars on a data set that does not change at sub-hourly cadence; longer than 14 d retention would store states whose application versions have already moved on. The 14 d window covers "I broke something last week and didn't notice."

---

## 2. Preconditions (run before any restore)

Before *any* restore procedure, confirm the green-state baseline:

```bash
# 1. Velero is healthy
kubectl -n velero get deploy/velero -o jsonpath='{.status.conditions[?(@.type=="Available")].status}'
# expect: True

# 2. The S3 backup location is reachable
velero backup-location get
# expect: default · Phase: Available

# 3. There is a recent successful backup
velero backup get | head -5
# expect: most-recent entry's STATUS = Completed, AGE ≤ 24 h

# 4. SOPS decrypt still works (sanity for post-restore secrets)
sops -d k8s/apps/velero/secret.yaml >/dev/null && echo OK
```

If any of these fail, **do not attempt a restore.** Resolve the precondition first; restoring against a broken Velero install creates partial state that is harder to recover than the original loss.

---

## 3. Monthly Backup Verification

Goal: prove a recent backup exists, contains the expected resources, and is restorable in principle. **No restore is performed.** ~5 minutes.

```bash
# 3.1 List the last 5 backups
velero backup get | head -6

# 3.2 Inspect the most recent backup
BACKUP=$(velero backup get -o name | head -1 | cut -d'/' -f2)
velero backup describe "$BACKUP" --details

# 3.3 Confirm expected namespaces are present
velero backup describe "$BACKUP" --details \
  | awk '/Namespaces:/,/^$/' \
  | grep -E '(adguard|argocd|grafana|prometheus|tailscale|velero)'

# 3.4 Confirm zero errors / warnings
velero backup describe "$BACKUP" --details \
  | grep -E '^(Errors|Warnings):' \
  || echo "no errors/warnings reported"
```

Record the result in your monthly ops log (a one-line entry; do not open a runbook entry unless a verification fails).

---

## 4. Quarterly Restore Drill

Goal: prove the restore path actually works against a known-good backup, into an **isolated namespace** so the live cluster is not touched. ~15–30 min depending on namespace size.

!!! warning "Pick a non-critical namespace"
    `grafana` and `golink` are good drill targets. Avoid `argocd` (will fight live reconciliation) and `tailscale` (touches mesh state).

### 4.1 Drill procedure

```bash
# Choose target backup + target namespace
BACKUP=$(velero backup get -o name | head -1 | cut -d'/' -f2)
SRC_NS="grafana"
DR_NS="dr-test-grafana-$(date +%Y%m%d)"

# 4.1.1 Create the restore, remapping the source namespace to the drill namespace
velero restore create "${DR_NS}" \
  --from-backup "${BACKUP}" \
  --include-namespaces "${SRC_NS}" \
  --namespace-mappings "${SRC_NS}:${DR_NS}" \
  --restore-volumes=false \
  --wait

# 4.1.2 Verify
kubectl get ns "${DR_NS}"
kubectl -n "${DR_NS}" get all
velero restore describe "${DR_NS}" --details
```

Pass criteria:

- `velero restore describe` shows `Phase: Completed`, zero errors.
- Expected Deployment/Service/ConfigMap counts match the source namespace.
- No leftover `Pending` resources after 5 min.

### 4.2 Drill teardown (mandatory)

```bash
kubectl delete ns "${DR_NS}" --wait=true
```

The drill namespace must be deleted within 24 h. A lingering `dr-test-*` namespace is itself a finding — log it in [`../security/audit-history.md`](../security/audit-history.md).

### 4.3 Record the drill

Append one line to the runbook ledger (`docs/runbooks/README.md`):

```
| 2026-MM-DD | DR drill | grafana → dr-test-grafana-YYYYMMDD | Pass | <operator> |
```

---

## 5. Full-Cluster Restore (catastrophic loss)

Goal: rebuild the cluster from zero and restore application state from the most recent good backup. ~60–90 min total. This is the procedure to run after a [control plane recovery](control-plane-recovery.md) attempt has been ruled out, or after the AWS account has lost the cluster entirely (instance termination + EBS gone).

!!! danger "This procedure rebuilds production. Confirm with the operator before proceeding."
    The cluster will be unreachable for the duration. The home LAN devices that depend on AdGuard DNS will fail over to fallback resolvers — confirm fallbacks are configured on the router.

### 5.1 Sequence

| Step | Action | Verify |
|---|---|---|
| 1 | `make deploy` (Terraform + Ansible + ArgoCD baseline) | `kubectl get nodes -o wide` shows every node `Ready` |
| 2 | Wait for ArgoCD App-of-Apps to reach `Synced` (excluding stateful apps) | `make validate-argocd-synced` returns 0 |
| 3 | Confirm Velero is healthy (see §2) | `velero backup get` lists all retained backups |
| 4 | Identify target backup | `velero backup get \| head -3` — choose the latest `Completed` |
| 5 | Restore platform namespaces | see §5.2 below |
| 6 | Verify each app's contract | `make smoke-test` returns 0 |
| 7 | Re-enable schedules / external triggers | scheduler Lambda, drift-detection workflow |

### 5.2 Restore command

```bash
BACKUP=$(velero backup get -o name | head -1 | cut -d'/' -f2)

velero restore create "full-restore-$(date +%Y%m%d-%H%M)" \
  --from-backup "${BACKUP}" \
  --existing-resource-policy=update \
  --wait
```

- `--existing-resource-policy=update`: update the resources ArgoCD has already created from git with backup-side data (Secrets, ConfigMaps, PVCs). This is safe because the *desired state* (manifests) is in git; only the *observed state* (PV data, generated tokens) is being restored.
- **Do not use `--existing-resource-policy=none` against a live namespace.** That flag overwrites without merging and will destroy any newer state ArgoCD just reconciled.

### 5.3 Post-restore verification

```bash
# 1. Every restored namespace's resource counts match the backup
velero restore describe "$(velero restore get -o name | head -1 | cut -d'/' -f2)" --details

# 2. App-of-Apps reaches Synced + Healthy
make validate-argocd-synced

# 3. Smoke tests pass
make smoke-test

# 4. Observability gate (no OOMKilled, no CrashLoopBackOff)
kubectl port-forward -n prometheus svc/prometheus 9090:9090 &
PROMETHEUS_URL=http://localhost:9090 OBSERVATION_WINDOW=600 \
  python3 bin/post_deploy_observability_gate.py

# 5. SOPS canary
sops -d k8s/apps/argocd/secret.yaml >/dev/null && echo "SOPS OK"
```

---

## 6. Rollback

There is **no rollback for a restore that ran successfully** — the cluster is now in the post-restore state by definition. If the restore *fails partway*:

```bash
# Identify the failed restore
velero restore get | grep -i 'PartiallyFailed\|Failed'

# Read the failure log
velero restore logs <name>

# Decide: re-run vs. manual repair
# Re-run only after the cause of failure has been fixed (e.g., bumped CRD,
# missing namespace label). Never re-run blindly — Velero is not idempotent
# on PartiallyFailed restores; resources already restored will be re-attempted
# and may conflict.
```

If the failed restore has left the cluster in a worse state than before, the recovery is a fresh `make deploy` from a healthy backup, **not** a second `velero restore` over the partial state.

---

## 7. Failure Modes and Recovery

| Symptom | Likely cause | First check |
|---|---|---|
| `velero backup get` empty | IAM user lost S3 permissions, or schedule deleted | `kubectl -n velero logs deploy/velero \| tail -50` for `AccessDenied`; check [`infra/aws/`](../../infra/aws/) Velero IAM block |
| Latest backup `PartiallyFailed` | A CRD changed between backup runs; Velero can't snapshot the new shape | `velero backup logs <name>`; add the CRD to the schedule's `includedResources` or accept the gap until the next run |
| Restore stuck `InProgress` for >30 min | Cluster has no scheduling capacity for the restored pods | `kubectl get events -A \| grep -i pending`; relieve scheduling pressure (see [`rpi-oom-mitigation.md`](rpi-oom-mitigation.md)) |
| Restored Secrets fail to decrypt | Restoring across a SOPS key rotation boundary | Rotate the cluster's age key back to the boundary's recipient; see [`sops-key-rotation.md`](sops-key-rotation.md) |
| S3 bucket lifecycle reaped a backup we wanted | Retention misalignment between bucket lifecycle and Velero schedule | Lifecycle is authoritative; treat the loss as final. Re-align in [`infra/aws/`](../../infra/aws/) and document in [`../security/audit-history.md`](../security/audit-history.md) |

---

## 8. Related

- **Velero service catalog page:** [`../services/velero.md`](../services/velero.md)
- **Backup/restore mechanics (broader):** [`../operations/backup-and-restore.md`](../operations/backup-and-restore.md)
- **Control plane unresponsive (before invoking DR):** [`control-plane-recovery.md`](control-plane-recovery.md)
- **SOPS key rotation:** [`sops-key-rotation.md`](sops-key-rotation.md)
- **RPi OOM mitigation (often unblocks a stuck restore):** [`rpi-oom-mitigation.md`](rpi-oom-mitigation.md)
- **Resource limits (capacity ceilings):** [`../operations/resource-limits.md`](../operations/resource-limits.md)
