# Terraform Operations

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

How to plan, apply, and tear down the AWS infrastructure. Architecture and module-level details live in [`../architecture/aws-infrastructure.md`](../architecture/aws-infrastructure.md). Cost details live in [`cost-and-scheduling.md`](cost-and-scheduling.md).

---

## TL;DR

```bash
make terraform-init      # one-time per machine
make terraform-plan      # review changes
make terraform-apply     # provision (or update)
make terraform-output    # IPs, kubeconfig command, scheduler URL
```

All targets are defined in the root [`Makefile`](../../Makefile) and ultimately invoke `terraform` in [`infra/aws/`](../../infra/aws/) with the right `AWS_PROFILE` and `SOPS_AGE_KEY_FILE` from [`.mise.toml`](../../.mise.toml).

---

## One-Time Bootstrap

The first deployment ever needs three things created **once**, in order:

### 1. State backend (`infra/aws-backend`)

Creates the S3 bucket `homelab-terraform-state-kkuhocyv` with versioning + encryption. Uses **local state** (intentional — bootstrapping the bucket that holds remote state).

```bash
cd infra/aws-backend
terraform init
terraform apply
```

After it completes, the main `infra/aws/main.tf` backend block points at the new bucket.

### 2. SOPS age key (workstation)

See [`sops-setup.md`](sops-setup.md). Without this, `terraform plan` fails with `no SOPS data found`.

### 3. SOPS-encrypted secrets file

`infra/aws/terraform.tfvars.sops.yaml` must exist and contain three keys: `ssh_public_key`, `k3s_token`, `tailscale_auth_key`. The catch-all rule in [`.sops.yaml`](../../.sops.yaml) auto-encrypts on save.

### 4. (Optional) GitHub Actions OIDC (`infra/aws-oidc`)

For CI's read-only `terraform plan`. Run once locally to provision the IAM OIDC provider and `terraform plan` role.

```bash
make oidc-init
make oidc-plan
make oidc-apply
make oidc-output     # role ARN to paste into GitHub repo secrets / variables
```

---

## Daily Workflow

### Plan a change

```bash
make terraform-plan
```

This runs `terraform plan` from `infra/aws/`. The plan is captured to `tfplan.binary` for `make terraform-apply` to consume.

### Apply

```bash
make terraform-apply
```

Applies `tfplan.binary` if present (no extra prompt), otherwise re-plans and applies. Spot instances may take 1–2 min to come up; total apply time is usually 3–5 min.

### Inspect outputs

```bash
make terraform-output
```

Useful outputs:

| Output | What it tells you |
|---|---|
| `k3s_server_public_ip` / `k3s_server_private_ip` | EC2 IPs (use Tailscale instead, but useful for SSM) |
| `k3s_server_instance_id` | Pass to `aws ssm start-session --target <id>` |
| `kubeconfig_command` | `scp` command to grab the k3s kubeconfig |
| `scheduler_function_url` | Manual start/stop endpoint |
| `manual_start_command` / `manual_stop_command` | Pre-baked AWS CLI commands |
| `estimated_monthly_cost_usd` | The official cost figure |

### Refresh state without changing anything

```bash
make terraform-state    # equivalent to: terraform refresh + terraform state list
```

---

## Variable Overrides

Defaults live in [`infra/aws/variables.tf`](../../infra/aws/variables.tf). To override locally, create `infra/aws/terraform.tfvars` (gitignored):

```hcl
# infra/aws/terraform.tfvars
server_instance_type = "t3.small"     # downsize for testing
ebs_volume_size      = 50
enable_scheduling    = false           # 24/7 mode
schedule_start_hour  = 8               # earlier start
```

For the full variable matrix see [`../architecture/aws-infrastructure.md#variables-defaults`](../architecture/aws-infrastructure.md#variables-defaults).

---

## LocalStack (Offline Plan Validation)

LocalStack lets you `terraform plan` without an AWS account. It validates module structure, variables, and resource dependencies — but **not** EC2 provisioning, IAM, or k3s installation.

```bash
docker run -d --name localstack -p 4566:4566 -e SERVICES=ec2,iam,ssm localstack/localstack:3.8.1
sleep 15
cd infra/aws
python3 scripts/validate_localstack.py
```

The wrapper script swaps in `provider_override.tf`, runs `terraform init/validate/plan -var-file=terraform.tfvars.localstack`, and tears down. Full procedure: [`testing.md#localstack`](testing.md#localstack).

---

## Destroying Infrastructure

```bash
make destroy
```

Interactive confirmation. After completion, three things remain:

- The S3 state bucket itself (run `infra/aws-backend` destroy to remove)
- The SSM transfer bucket (deleted by the destroy if `force_destroy = true` is set, which it is)
- Any leftover EBS snapshots from spot interruptions — clean these manually:
  ```bash
  aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].SnapshotId' --output text \
    | xargs -n1 aws ec2 delete-snapshot --snapshot-id
  ```

For a more thorough teardown including orphaned resources, run [`infra/aws/scripts/clean_lab.py`](../../infra/aws/scripts/clean_lab.py) (uses `aws-nuke` patterns).

---

## State Operations

### View state list

```bash
cd infra/aws && terraform state list
```

### Inspect a resource

```bash
terraform state show 'module.k3s_cluster.aws_spot_instance_request.k3s_server'
```

### Move a resource (rare)

```bash
terraform state mv 'module.old.<resource>' 'module.new.<resource>'
```

### Pull / push state (very rare — backups only)

```bash
terraform state pull > backup.tfstate
# edit if necessary
terraform state push backup.tfstate
```

---

## Cheat Sheet

```bash
# Health
make terraform-output                     # dump all outputs
terraform output -json | jq               # JSON-formatted outputs

# Spot instance status
aws ec2 describe-spot-instance-requests --filters "Name=tag:Project,Values=Lab-DevOps-Pro"

# Force a fresh AMI lookup (e.g., new Amazon Linux 2023 release)
terraform apply -replace='module.k3s_cluster.aws_launch_template.k3s'

# Run terraform plan that ignores SOPS (for CI)
terraform plan -var='localstack_test=yes' -var-file=terraform.tfvars.localstack

# See what changed since last apply
terraform plan -refresh=false
```

---

## Troubleshooting

### `no SOPS data found in file`
The secrets file isn't encrypted. See [`sops-setup.md`](sops-setup.md).

### `Error: could not decrypt data key with any master key`
`SOPS_AGE_KEY_FILE` not set or pointing at the wrong key. Check `mise env` shows `SOPS_AGE_KEY_FILE=/home/vscode/.config/sops/age/keys.txt`.

### `Error: spot instance request status: capacity-not-available`
AWS doesn't have spot capacity for `t3.medium` in the AZ. Re-run `terraform apply` (the persistent spot request will retry), or temporarily switch to `t3.small` via `terraform.tfvars`.

### `Error: VPCIdNotSpecified`
The default VPC was deleted. Recreate it (`aws ec2 create-default-vpc`) or pin a specific VPC ID by editing the network module.

### `terraform plan` shows the SSM bucket recreating every time
Confirm `force_destroy = true` is in [`infra/aws/main.tf:116`](../../infra/aws/main.tf) and that nothing else is mutating the bucket out-of-band.

### `terraform plan` hangs on `data.sops_file.secrets`
Network problem reaching the encrypted file? Run `sops -d infra/aws/terraform.tfvars.sops.yaml | head -3` to confirm decryption works at all.

---

## CI Integration

| Workflow | What it does |
|---|---|
| [`.github/workflows/ci-validation.yml`](../../.github/workflows/ci-validation.yml) | `terraform fmt -check`, `terraform validate`, `tflint`, `terraform plan` (against LocalStack), Conftest policy checks |
| [`.github/workflows/ci-deployment.yml`](../../.github/workflows/ci-deployment.yml) | Real `terraform apply` on `main` push (gated, OIDC-authenticated) |

CI never has the SOPS age key. It plans with `localstack_test=yes` so the SOPS data source is bypassed.

---

## Related

- **Architecture:** [`../architecture/aws-infrastructure.md`](../architecture/aws-infrastructure.md)
- **Cost & scheduler:** [`cost-and-scheduling.md`](cost-and-scheduling.md)
- **Secrets workflow:** [`sops-setup.md`](sops-setup.md)
- **Test the modules without spending money:** [`testing.md`](testing.md)
