# Runbook: Restore the k3s control-plane from an S3 snapshot (Pi-only)

> **Status:** Active · **Owner:** @ariel-extending851
> **Companion to:** [`control-plane-recovery.md`](control-plane-recovery.md),
> [`disaster-recovery-velero.md`](disaster-recovery-velero.md)

## What this covers

The k3s server runs the **SQLite** datastore (`cluster-init: false`), so k3s's
native etcd snapshots do not apply. The `k8s/apps/k3s-snapshot` CronJob backs up
`state.db` to S3 every 12h (online `sqlite3 .backup` → gzip → upload), giving an
**offsite** copy of the control-plane state — the SD card is no longer the only
place the cluster's identity lives.

This restores that state after losing the control-plane node (dead SD card,
corrupted `state.db`, bad upgrade). Velero restores *application* namespaces and
PVCs; this restores the *datastore* (nodes, RBAC, CRDs, ServiceAccount tokens,
everything the apiserver serves). Use both for a full rebuild.

## Snapshot location

```
s3://homelab-velero-backups-kkuhocyv/cluster-state/<node>/<UTC-timestamp>-state.db.gz
```

The uploader IAM user (`hl-k3s-snapshot`) is **write-only** by design, so the
restore below uses **admin/operator AWS credentials** (your own, or the Velero
user's keys from `terraform -chdir=infra/aws-velero output`), not the uploader's.

## Restore procedure (on the control-plane node)

> ⚠️ Destructive: replaces the live datastore. Per CLAUDE.md principle #4, this
> is a human-confirmed action. Take a copy of the current `state.db` first.

```bash
# 1. List available snapshots (admin creds) and pick the most recent good one.
aws s3 ls s3://homelab-velero-backups-kkuhocyv/cluster-state/rasp-pi-04/

# 2. Stop k3s so the datastore is quiescent.
sudo systemctl stop k3s

# 3. Pull + decompress the chosen snapshot.
cd /tmp
aws s3 cp s3://homelab-velero-backups-kkuhocyv/cluster-state/rasp-pi-04/<TS>-state.db.gz .
gunzip <TS>-state.db.gz   # -> <TS>-state.db

# 4. Back up the current datastore, then swap in the snapshot.
DB=/var/lib/rancher/k3s/server/db/state.db
sudo cp -a "$DB" "${DB}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -o root -g root -m 0600 /tmp/<TS>-state.db "$DB"

# 5. Start k3s and verify.
sudo systemctl start k3s
sudo k3s kubectl get nodes        # control plane Ready
sudo k3s kubectl get applications -n argocd   # ArgoCD reconciles the rest
```

The agent node (`rasp-pi-03`) rejoins automatically once the apiserver is back —
its node object and token live in the restored datastore. If it does not, re-run
the k3s role from `ansible/` to re-register it.

## After restore

- Reconcile workloads/PVCs with Velero if app data also needs rolling back —
  see [`disaster-recovery-velero.md`](disaster-recovery-velero.md).
- If the snapshot predates a recent secret/credential rotation, re-bootstrap
  those (e.g. `make velero-bootstrap-secret`, `make k3s-snapshot-bootstrap-secret`).
- Remove the `${DB}.bak.*` copy once the cluster is confirmed healthy.

## Validate the backup is actually running

```bash
kubectl -n k3s-snapshot get cronjob k3s-snapshot
kubectl -n k3s-snapshot get jobs            # recent successful runs
aws s3 ls s3://homelab-velero-backups-kkuhocyv/cluster-state/rasp-pi-04/ | tail
```

A missing/stale object here means the control plane is unprotected — investigate
the CronJob (creds via `make k3s-snapshot-bootstrap-secret`, NetworkPolicy egress,
node affinity) before assuming you have a restore path.
