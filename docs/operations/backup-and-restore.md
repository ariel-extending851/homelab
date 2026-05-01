# Backup & Restore Operations

> **Status:** Active · **Last reviewed:** 2026-05-01
> **Owner:** @ariel-extending851

Operational guide for cluster-state backups and restore drills. Architecture, IAM, and storage layout are described in [`../services/velero.md`](../services/velero.md); this doc covers *how to run them*.

---

## Schedule (automatic)

Velero `Schedule` `daily-backup` runs at **14:00 UTC (11:00 BRT)**, inside the AWS scheduler's daily window so the AWS k3s nodes are guaranteed up. Retention is 14 days.

```bash
velero backup get | head -10
velero schedule get
```

A pre-deploy safety backup is also taken automatically before risky CI deploys via [`bin/velero_pre_deploy_backup.py`](../../bin/velero_pre_deploy_backup.py). The script names the backup `pre-deploy-<gitsha>-<timestamp>` and waits for completion before the deploy proceeds.

---

## Trigger an ad-hoc backup

```bash
velero backup create manual-$(date +%Y%m%d-%H%M%S) \
  --include-namespaces adguard,argocd,golink,grafana,loki,otel-collector,prometheus,tailscale,velero
velero backup logs <name>
velero backup describe <name>
```

Use this before high-risk operations (CRD upgrade, ArgoCD root migration, k3s version bump).

---

## Restore drill (`make test-velero-restore`)

The end-to-end test in [`bin/tests/e2e_post_deploy.bats`](../../bin/tests/e2e_post_deploy.bats) creates a backup, deletes a target, restores from the backup, and asserts data integrity.

```bash
# Requires: live cluster, kubectl configured, Velero installed, AWS creds in place
make test-velero-restore
```

The test:

1. Creates a Velero `Backup` of one namespace (default: `golink`)
2. Deletes the deployment + PVC
3. Issues `velero restore create --from-backup <name>`
4. Polls for restore `Phase=Completed`
5. Asserts the deployment, service, and PV-bound pod are back

Run quarterly. Log the result (date, duration, any deviation) — see the DR drill log section below.

---

## Manual restore (incident playbook)

```bash
# 1. Pick a backup. Newest first.
velero backup get

# 2. Restore into a fresh namespace OR replace existing
velero restore create --from-backup <name> \
  --include-namespaces grafana
velero restore logs --tail=100 <restore-name>

# 3. Verify
kubectl get pods,svc,pvc -n grafana
```

Recovery time targets:
- **Cluster state**: < 30 min from "fresh cluster" to all apps Running.
- **Largest PVC** (Loki 10 Gi): < 60 min.

If the cluster is gone entirely, rebuild the nodes first via `ansible/roles/emergency_recovery` + `terraform apply`, then run `make velero-bootstrap-secret` to inject AWS credentials before the restore.

---

## DR drill log

Log every drill in `docs/operations/dr-drill-log.md` (TBD — create on first drill). Capture:

- Date, operator, duration
- Backup id used
- Anything that diverged from the playbook
- Action items

---

## Related

- [`../services/velero.md`](../services/velero.md) — architecture, IAM, storage
- [`../runbooks/on-call.md`](../runbooks/on-call.md) — incident triage
- [`../security/overview.md`](../security/overview.md) — backup is part of the threat model (ransomware mitigation)
