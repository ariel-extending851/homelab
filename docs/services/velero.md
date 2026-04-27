# Velero — Cluster Backup & Disaster Recovery

> **Status:** Stub (manifests committed, not yet deployed)
> **Last reviewed:** 2026-04-27
> **Owner:** @ariel-extending851

Cluster-state backup operator. Snapshots K8s resources (Deployments, ConfigMaps, Secrets, etc.) and PVCs, uploads to S3. Complements `ansible/roles/emergency_recovery` (which rebuilds *nodes*) by recovering *cluster state* after data loss.

## Architecture

| Component | Role |
|---|---|
| Controller (`Deployment`) | Watches `Backup`/`Restore`/`Schedule` CRDs, drives the lifecycle. |
| node-agent (`DaemonSet`) | restic uploader on each node — copies PVC bytes to S3. Excludes `rasp-pi-03` (1GB RAM too tight). |
| `BackupStorageLocation` (CRD) | Points Velero at the S3 bucket `homelab-velero-backups`. |
| `Schedule` (CRD) `daily-backup` | Runs at 14:00 UTC (11:00 BRT) — inside the AWS scheduler's daily window. Retention 14d. |
| AWS S3 bucket | Versioned, AES256-encrypted, lifecycle: Standard → IA (30d) → Glacier (90d) → expire (365d). |
| IAM user `homelab-velero` | Least privilege — only S3 access scoped to the backup bucket. Static credentials in SOPS-encrypted Secret (k3s has no IRSA). |

## Wildcard RBAC

Velero needs to reify *any* CRD that may exist in the cluster (now or later) for a complete backup. Enumerating resources risks silent backup gaps. The `velero` ClusterRole is on the `wildcard_allowed_clusterroles` allowlist in [`k8s/policies/rbac_safety.rego`](../../k8s/policies/rbac_safety.rego); see [`k8s/policies/README.md`](../../k8s/policies/README.md) for the justification record.

## Bootstrap (post-`make deploy`)

CRDs are vendored in [`crds.yaml`](../../k8s/apps/velero/crds.yaml) with `argocd.argoproj.io/sync-wave: "-2"` — ArgoCD applies them before any `BackupStorageLocation` / `Schedule` resource. AWS credentials are injected via a single idempotent Make target after Terraform creates the IAM user.

```bash
# 1. Full deploy: AWS infra + k3s + ArgoCD + apps (Velero CRDs ship with the manifests)
make deploy

# 2. Inject AWS credentials into the SOPS Secret (idempotent — safe to re-run)
make velero-bootstrap-secret

# 3. Commit + push so ArgoCD syncs the patched secret
git add k8s/apps/velero/secret.yaml
git commit -S -m "chore(velero): bootstrap AWS creds"
git push

# 4. Verify (ArgoCD picks up automatically within ~3 min)
kubectl get pods -n velero
kubectl get backupstoragelocation -n velero
kubectl get schedule -n velero
```

**Idempotency**: `make velero-bootstrap-secret` reads the current `terraform output` and re-encrypts in place. Run it again whenever Terraform recreates the IAM access key (rotation, cluster rebuild) — the diff in `secret.yaml` will reflect the new credential.

### What the target does

1. `terraform output -raw velero_aws_access_key_id`
2. `terraform output -raw velero_aws_secret_access_key`
3. `sops --decrypt k8s/apps/velero/secret.yaml` → tempfile `mode=0o600`
4. Patch the `stringData.cloud` block with the new INI credentials
5. `sops --encrypt --in-place` the tempfile, then atomic `os.replace` over the original
6. Tempfile unlinked in `try/finally` — plaintext never persists

Source: [`bin/velero_bootstrap_secret.py`](../../bin/velero_bootstrap_secret.py).

### CRD refresh (rare — when bumping Velero version)

```bash
# Fetch each CRD from the upstream tag, concatenate, inject sync-wave annotation
# See the helper script comment block at top of k8s/apps/velero/crds.yaml
```

## Operations

### Trigger an ad-hoc backup

```bash
velero backup create manual-$(date +%Y%m%d-%H%M%S) \
  --include-namespaces adguard,argocd,golink,grafana,loki,monitoring,otel-collector,prometheus,tailscale,velero
velero backup logs manual-...
```

### Restore drill

```bash
# 1. Pick a backup
velero backup get

# 2. Restore into a fresh namespace (or replace existing)
velero restore create --from-backup <name> --include-namespaces grafana

# 3. Verify
kubectl get pods,svc,pvc -n grafana
```

### Inspect storage

```bash
velero backup-location get
velero backup describe <name>
aws s3 ls s3://homelab-velero-backups/cluster-backups/
```

## Recovery time objective (target)

- **Cluster state**: < 30 min from "fresh cluster" to "all 9 apps running" via `velero restore`.
- **PVC data**: < 60 min for the largest PVC (Loki 10Gi).
- Drill quarterly, log results in [`docs/operations/dr-drill-log.md`](../operations/dr-drill-log.md) (TBD).

## Resource cost

| Component | Requests | Limits |
|---|---|---|
| Controller | 100m / 150Mi | 500m / 256Mi |
| node-agent (×3 nodes — Pi3 excluded) | 50m / 64Mi each | 300m / 200Mi each |
| **Cluster total** | ~250m / 342Mi | — |

## What this does NOT cover

- AWS infrastructure (EC2, EBS) — covered by `ansible/roles/emergency_recovery` + Terraform re-apply.
- Tailscale tailnet state — Tailscale is the source of truth; nodes re-auth automatically.
- ArgoCD root config — bootstrapped by `ansible/roles/argocd` separately.
