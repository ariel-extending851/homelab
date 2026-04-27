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

## Bootstrap (one-time, post-`terraform apply`)

```bash
# 1. Apply Terraform (creates bucket + IAM user + access key)
make terraform-apply

# 2. Read credentials from outputs
ACCESS_KEY=$(terraform -chdir=infra/aws output -raw velero_aws_access_key_id)
SECRET_KEY=$(terraform -chdir=infra/aws output -raw velero_aws_secret_access_key)

# 3. Patch the Velero secret manifest with real creds, then SOPS-encrypt
cat > /tmp/velero-cloud.txt <<EOF
[default]
aws_access_key_id = ${ACCESS_KEY}
aws_secret_access_key = ${SECRET_KEY}
EOF

# Edit k8s/apps/velero/secret.yaml: replace the `cloud:` stringData value with /tmp/velero-cloud.txt
sops --encrypt --in-place k8s/apps/velero/secret.yaml

# 4. Install Velero CRDs (one-time, before ArgoCD syncs the schedule resource)
kubectl apply -f https://github.com/vmware-tanzu/velero/releases/download/v1.14.1/velero-crds-v1.14.1.yaml

# 5. ArgoCD picks up the manifests on next sync; verify:
kubectl get pods -n velero
kubectl get backupstoragelocation -n velero
kubectl get schedule -n velero
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
