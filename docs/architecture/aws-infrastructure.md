# AWS Infrastructure

> **Status:** Active
> **Last reviewed:** 2026-05-01
> **Owner:** @ariel-extending851

Terraform-managed AWS infrastructure for the k3s control plane and one worker. Four modules: `network`, `compute`, `scheduler`, `audit`. Plus an SSM transfer bucket and OIDC bootstrap.

---

## Module Layout

| Module | Path | Purpose |
|---|---|---|
| `network` | [`infra/aws/modules/network`](../../infra/aws/modules/network) | Default VPC, subnets, security group |
| `compute` | [`infra/aws/modules/compute`](../../infra/aws/modules/compute) | EC2 spot instances, IAM, SSH key, launch templates |
| `scheduler` | [`infra/aws/modules/scheduler`](../../infra/aws/modules/scheduler) | Lambda + EventBridge for start/stop schedule |
| `audit` | [`infra/aws/modules/audit`](../../infra/aws/modules/audit) | CloudTrail (management events) + GuardDuty (regional detector); cost-bounded < $5/mo |
| `aws-backend` (separate) | [`infra/aws-backend`](../../infra/aws-backend) | One-time bootstrap of S3 state bucket |
| `aws-oidc` (separate) | [`infra/aws-oidc`](../../infra/aws-oidc) | OIDC provider + IAM role for GitHub Actions |

---

## Backend & Provider

```hcl
# infra/aws/main.tf:14-39
terraform {
  required_version = ">= 1.5.0"
  backend "s3" {
    bucket       = "homelab-terraform-state-kkuhocyv"
    key          = "homelab/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true   # supersedes the deprecated DynamoDB lock table (TF >= 1.10)
    encrypt      = true
  }
  required_providers {
    aws       = "~> 5.0"
    sops      = "~> 0.7.0"
    tailscale = "~> 0.13"
  }
}
```

Default tags applied to all resources: `Project=Lab-DevOps-Pro`, `ManagedBy=Terraform`, `Environment=homelab`.

---

## Variables (Defaults)

| Variable | Default | Validation | Notes |
|---|---|---|---|
| `aws_region` | `us-east-1` | — | |
| `server_instance_type` | `t3.medium` | t3.{micro,small,medium} | Control plane |
| `agent_instance_type` | `t3.small` | t3.{micro,small,medium} | Worker |
| `ebs_volume_size` | `30` | 30–100 GB | gp3, encrypted |
| `spot_max_price` | `""` | — | Empty = on-demand price as max |
| `ssh_key_name` | `hl-homelab-key` | — | |
| `k3s_version` | `v1.34.3+k3s1` | regex | Pinned |
| `enable_scheduling` | `true` | — | |
| `schedule_timezone` | `America/Sao_Paulo` | IANA | |
| `schedule_start_hour` | `10` | 0–23 | 10:00 BRT |
| `schedule_stop_hour` | `21` | 0–23 | 21:00 BRT |
| `ssm_s3_bucket` | `homelab-ssm-transfer-bucket` | — | **Must differ from state bucket** |
| `localstack_test` | `"no"` | yes/no | Switches to mock secrets |

Source: [`infra/aws/variables.tf`](../../infra/aws/variables.tf).

---

## Network Module

Uses the **default VPC** (cost optimization — no NAT gateway, no per-AZ ENI charges) with multi-AZ default subnets. One security group named `hl-k3s-cluster`:

- **Inbound:** all traffic from itself (intra-cluster). No public ingress for SSH or k3s API.
- **Outbound:** all (eg. pulling container images, joining tailnet).

All operator access is via Tailscale or AWS SSM Session Manager. Outputs: `vpc_id`, `vpc_cidr`, `subnet_ids`, `security_group_id`, `security_group_name`.

---

## Compute Module

Provisions both EC2 instances as **persistent spot requests** (auto-replacing) on the latest Amazon Linux 2023 AMI (`al2023-ami-*-x86_64`).

Per-instance:

- **IAM:** instance profile with `AmazonSSMManagedInstanceCore` + inline policy granting `s3:GetObject`/`s3:PutObject` on the SSM transfer bucket only
- **EBS:** 30 GB gp3, encrypted at rest
- **IMDSv2:** required (token-bound)
- **User data:** k3s install script (server or agent) with token + Tailscale auth key from SOPS
- **Tags:** `Name=hl-k3s-server-01` / `hl-k3s-agent-01`, plus `Role=server|agent`

Outputs include both public and private IPs, instance IDs, and convenience `ssh`/`scp` commands. Real connectivity should use Tailscale IPs; the public IPs are mostly informational since no port is open from the internet.

---

## Scheduler Module

Lambda + EventBridge that issue `StartInstances` / `StopInstances` calls on a daily schedule.

- **Runtime:** Python 3.x
- **Cron:** computed from `schedule_timezone` + `schedule_start_hour` + `schedule_stop_hour` (default 10:00 and 21:00 America/Sao_Paulo)
- **Function URL:** issued, allowing manual `curl -X POST` from anywhere with the URL
- **Outputs:** `lambda_function_url`, `manual_start_command`, `manual_stop_command`, `manual_status_command`, `schedule_summary`

Disabled by setting `enable_scheduling = false` (or implicitly when `localstack_test = "yes"`). Cost impact analysis: [`../operations/cost-and-scheduling.md`](../operations/cost-and-scheduling.md).

---

## Audit Module

Forensic trail + threat detection, intentionally minimal to stay under ~$5/month at homelab volume.

- **CloudTrail** — single trail, **management events only**, single-region. Multi-region trails and S3 data events are deliberately disabled (cost). Logs land in a dedicated S3 bucket with versioning, AES256, public-access blocked, and lifecycle: Standard → IA (30d) → Glacier (90d) → expire (365d). `force_destroy=false` to prevent accidental deletion of evidentiary logs.
- **GuardDuty** — single regional detector with default 6h finding-publishing frequency. After the 30-day free trial expects $0.50–$2/month.
- **Out of scope by design:** AWS Config, Security Hub, Macie, multi-region trails, EventBridge fan-out — all priced beyond the homelab cost envelope.

Source: [`infra/aws/modules/audit/main.tf`](../../infra/aws/modules/audit/main.tf). Reviewed in CI by `make plan-audit` (Terraform plan diff fed through Infracost gate — see [`../operations/cost-controls.md`](../operations/cost-controls.md)).

---

## SSM Transfer Bucket

A **separate** S3 bucket (`homelab-ssm-transfer-bucket` by default) used by the Ansible `community.aws.aws_ssm` connection plugin to relay stdin/stdout when running playbooks against EC2.

- **Critical:** must be different from the Terraform state bucket. Compromised nodes have read/write here, and we don't want them able to read decrypted secrets in state files.
- **Versioning:** on
- **Encryption:** SSE-S3 (AES256)
- **Public access:** fully blocked
- **Lifecycle:** delete objects after 7 days; non-current versions after 1 day

Defined inline in [`infra/aws/main.tf`](../../infra/aws/main.tf) (lines 110–175).

---

## Bootstrap Modules (`aws-backend`, `aws-oidc`)

Both are run **once**, locally, with their own local state.

### `infra/aws-backend`
Creates the S3 state bucket (`homelab-terraform-state-kkuhocyv`) with versioning and encryption. After this completes, the main `infra/aws` module switches to the S3 backend. Required Terraform: `>= 1.7.0`.

### `infra/aws-oidc`
Creates the GitHub Actions OIDC provider in IAM and a read-only `terraform plan` role scoped to `repo:ariel-extending851/homelab:*`. This is what the CI plan jobs assume — there are no static AWS credentials in GitHub. OIDC thumbprint pinned to `6938fd4d98bab03faadb97b34396831e3780aea1`.

> **Note:** the legacy account name `ariel99gf` no longer appears in the trust policy; the OIDC sub matches the canonical repo URL `ariel-extending851/homelab`. After re-running `make oidc-apply`, AWS will rotate the trust policy's `sub` condition.

---

## Cost Snapshot

Computed in [`infra/aws/outputs.tf:68-71`](../../infra/aws/outputs.tf):

| Mode | Estimate |
|---|---|
| With scheduling (default, ~45% uptime) | **~$24.59 / month** |
| 24/7 (`enable_scheduling = false`) | ~$45.55 / month |

Full breakdown and the resolution of older conflicting numbers: [`../operations/cost-and-scheduling.md`](../operations/cost-and-scheduling.md).

---

## Where to Go Next

- **Operate it:** [`../operations/terraform.md`](../operations/terraform.md)
- **Test changes locally with LocalStack:** [`../operations/testing.md`](../operations/testing.md)
- **Network details:** [`networking.md`](networking.md)
- **Secrets handling:** [`secrets-management.md`](secrets-management.md)
