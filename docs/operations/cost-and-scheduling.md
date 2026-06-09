# Cost and Scheduling

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

This is the **single source of truth** for the AWS monthly cost estimate. Older docs (`infra/aws/main.tf`, `infra/aws/README.md`, `QUICKSTART.md`, `DEPLOYMENT-SUMMARY.md`) had three different numbers — they're being corrected to match this page.

---

## Current Cost Estimate

Computed in [`infra/aws/outputs.tf:68-71`](../../infra/aws/outputs.tf), based on the current variable defaults (`server_instance_type = t3.medium`, `agent_instance_type = t3.small`, `ebs_volume_size = 30`):

| Mode | Estimate | When |
|---|---|---|
| With scheduling (default) | **~$24.59 / month** | `enable_scheduling = true`, ~45% daily uptime |
| 24/7 | ~$45.55 / month | `enable_scheduling = false` |

Get the live value:
```bash
make terraform-output    # or: cd infra/aws && terraform output estimated_monthly_cost_usd
```

### Breakdown (scheduling enabled)

Approximate, US-East-1, spot pricing as of April 2026:

| Item | Hours/month | Rate | Subtotal |
|---|---|---|---|
| t3.medium spot (server) | ~330 | ~$0.0125/hr | ~$4.13 |
| t3.small spot (agent)   | ~330 | ~$0.0062/hr | ~$2.05 |
| EBS gp3 30 GB × 2       | always | $0.08/GB-month | ~$4.80 |
| EBS snapshots (DLM, 7 daily, incremental) | — | ~$0.05/GB-month | ~$1–3 |
| Lambda invocations (scheduler) | 60/mo | free tier | ~$0.00 |
| EventBridge rules | 3 | free tier | ~$0.00 |
| S3 (state + SSM transfer) | low traffic | — | ~$0.50 |
| ECR private registry | ≤500 MB | free tier (12 mo) | ~$0.00 |
| SNS / Budgets / Cost Anomaly / Access Analyzer | — | free | ~$0.00 |
| CloudWatch billing alarm | 1 | first 10 free | ~$0.00 |
| Data transfer (intra-AZ + Tailscale outbound) | varies | — | ~$2.00 |
| **NAT/IGW** | **none** | **(default VPC, no NAT)** | **$0.00** |
| Slack for over-provisioning | — | — | ~$10.00 |
| **Total** | | | **~$25–27** |

The $10 slack covers spot price spikes, EBS snapshot growth, and a margin for occasional 24/7 runs. The new guardrails (below) are free; the only new run-rate is incremental EBS snapshot storage from DLM (~$1–3/month).

---

## Cost & security guardrails (free)

Created by [`infra/aws/modules/finops`](../../infra/aws/modules/finops) and [`infra/aws/modules/backup-ebs`](../../infra/aws/modules/backup-ebs). Until these existed, the only cost signal was the Infracost PR gate — nothing watched **actual** account spend.

| Guardrail | What it does | Cost |
|---|---|---|
| AWS Budgets (`hl-monthly-cost`) | Alerts at 80% / 100% actual + 100% forecasted of `monthly_budget_usd` (default $30) | Free (first 2 budgets) |
| Cost Anomaly Detection | ML alert on a single runaway service (e.g. spot spike), impact ≥ `anomaly_impact_threshold_usd` ($10) | Free |
| CloudWatch billing alarm | Backstop when `EstimatedCharges` > `billing_alarm_usd` (default $35) | Free (first 10 alarms) |
| IAM Access Analyzer | Flags any S3 bucket / IAM role reachable from outside the account | Free (ACCOUNT type) |
| EBS snapshot lifecycle (DLM) | Daily snapshots of both k3s volumes, retain `snapshot_retain_count` (default 7) | DLM free; storage ~$0.05/GB-month |

All alerts (cost + GuardDuty/Access Analyzer findings) fan out through one SNS topic `hl-cost-alerts`. Set `alert_email` to receive them and **confirm the subscription** — see [`cost-controls.md`](cost-controls.md).

---

## Schedule

| Action | Default | Variable |
|---|---|---|
| Start instances | 10:00 | `schedule_start_hour` |
| Stop instances | 21:00 | `schedule_stop_hour` |
| Timezone | `America/Sao_Paulo` (BRT/BRST) | `schedule_timezone` |

The scheduler Lambda (created by [`infra/aws/modules/scheduler`](../../infra/aws/modules/scheduler)) is triggered by two EventBridge rules with cron expressions converted from `schedule_timezone` to UTC at apply time.

> **DST note**: `America/Sao_Paulo` does **not** currently observe daylight saving time (Brazil ended DST in 2019). The UTC offset is stable at -03:00 year-round, so the cron expressions are `0 13 * * ? *` (start) and `0 0 * * ? *` (stop) — that is, 13:00 UTC and 00:00 UTC. If Brazil reinstates DST, the apply will need to re-render the cron.

### Manual control

After `terraform apply`, three commands are echoed in the outputs:

```bash
terraform output manual_start_command
terraform output manual_stop_command
terraform output scheduler_function_url
```

Or hit the Lambda function URL directly:
```bash
curl -X POST "$(terraform output -raw scheduler_function_url)" -d '{"action":"start"}'
curl -X POST "$(terraform output -raw scheduler_function_url)" -d '{"action":"stop"}'
curl -X POST "$(terraform output -raw scheduler_function_url)" -d '{"action":"status"}'
```

---

## Disabling the scheduler

```hcl
# infra/aws/terraform.tfvars  (or override on the command line)
enable_scheduling = false
```

This destroys the Lambda + EventBridge resources and leaves the EC2 instances running 24/7. The estimated cost output flips to `~$45.55 / month`.

---

## Cost surprises to watch for

- **EBS snapshot growth** if you take ad-hoc snapshots before destroys. Clean with:
  ```bash
  aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[?StartTime<=`2026-01-01`].SnapshotId' --output text | \
    xargs -n1 aws ec2 delete-snapshot --snapshot-id
  ```
- **Spot interruption then no capacity** — instances stay in the `terminated` state until the spot request retries. The persistent spot request will keep retrying, but you may see a gap in monitoring.
- **Cross-AZ data transfer** if pods land on a node in a different AZ from their PV. Both EC2 instances are normally in the same default-VPC default subnet, so this should be zero.
- **Lambda function URL abuse** — the URL is unauthenticated. Treat it as a secret. If leaked, rotate by re-applying with a forced replacement of the function or by adding URL auth (currently `NONE`).

---

## Old / Stale Numbers

Prior to this consolidation, three different cost figures appeared in docs. All have been (or will be) corrected to point here:

| Source | Old number | Status |
|---|---|---|
| `infra/aws/main.tf:5` | "~$17.65 USD/month (2× t3.small spot + 40GB gp3 EBS)" | Stale: agent is t3.small but server is t3.medium; EBS default is 30 GB not 40 GB. **Fix in PR3.** |
| `infra/aws/README.md:151` | "$15.65" line item for "2× t3.small Spot (730h)" | Stale: instance types and 730h assumes 24/7 uptime. **Replaced by stub in PR3.** |
| `QUICKSTART.md:117` | "$13/month w/ schedule" | Stale: predates the t3.medium upgrade. **Fix in PR6.** |
| `DEPLOYMENT-SUMMARY.md:160-161` | "BRT (1:00 PM UTC)" | Correct UTC math but no DST caveat. **Archived in PR6; replaced by the DST note above.** |
