# AWS Infrastructure

Terraform configuration for the k3s cluster on AWS EC2 spot instances.

For full documentation, see:

- **Architecture & module deep-dive:** [`docs/architecture/aws-infrastructure.md`](../../docs/architecture/aws-infrastructure.md)
- **Operations (apply, plan, destroy):** [`docs/operations/terraform.md`](../../docs/operations/terraform.md)
- **Cost & scheduling:** [`docs/operations/cost-and-scheduling.md`](../../docs/operations/cost-and-scheduling.md)
- **Secrets (SOPS + age):** [`docs/operations/sops-setup.md`](../../docs/operations/sops-setup.md)
- **LocalStack testing:** [`docs/operations/testing.md#localstack-terraform-without-aws`](../../docs/operations/testing.md#localstack-terraform-without-aws)

## Layout

| Path | Purpose |
|---|---|
| `main.tf`, `variables.tf`, `outputs.tf` | Root module |
| `modules/network/` | VPC + security group |
| `modules/compute/` | EC2 spot instances + IAM + SSH key |
| `modules/scheduler/` | Lambda + EventBridge for instance start/stop |
| `terraform.tfvars.sops.yaml` | SOPS-encrypted secrets (ssh_public_key, k3s_token, tailscale_auth_key) |
| `tests/` | `terraform test` (.tftest.hcl) suites |
| `scripts/` | LocalStack validation, AWS Nuke cleanup |
| `testing/` | LocalStack overrides and mock secrets |

## Quick start

```bash
make terraform-init
make terraform-plan
make terraform-apply
make terraform-output
```

Cost: ~$24.59/month with scheduling, ~$45.55/month 24/7 (see [`cost-and-scheduling.md`](../../docs/operations/cost-and-scheduling.md)).
