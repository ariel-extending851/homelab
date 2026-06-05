# Cost Controls

> **Status:** Active · **Last reviewed:** 2026-05-01
> **Owner:** @ariel-extending851

Three layers of cost governance: the **Infracost gate** in CI (catches regressions *before* merge), the **scheduling Lambda** that bounds runtime expense, and the **account-level alerts** (Budgets + Cost Anomaly Detection + billing alarm) that catch *actual* spend the first two can't see. Per-resource estimates and steady-state cost live in [`cost-and-scheduling.md`](cost-and-scheduling.md); this doc covers *the gate*, *the alerts*, and *what to do when they fire*.

---

## Infracost gate

Each Terraform PR runs `infracost diff` against the base branch. The diff JSON is fed to [`bin/infracost_diff_gate.py`](../../bin/infracost_diff_gate.py), which exits non-zero if `|diffTotalMonthlyCost|` exceeds the threshold (default **±$5/month**).

```bash
# Local invocation against an existing diff JSON
python3 bin/infracost_diff_gate.py \
  --diff /tmp/infracost-diff.json \
  --max-delta 5 \
  --summary "$GITHUB_STEP_SUMMARY"
```

The script writes a Markdown table (baseline / PR / delta / threshold) to `--summary`, used by GitHub's Step Summary so reviewers see the number directly on the PR.

---

## When the gate fires

A failing Infracost gate means the PR's Terraform plan would change AWS spend by more than the threshold. Order of operations:

1. **Read the Markdown summary** in the failed CI step. The delta is signed (`+` = more expensive, `−` = cheaper).
2. **Cheaper changes (`−$X`)** also fail the gate by absolute value — that's intentional. Often this is a real save, just confirm and bump the threshold for that PR or split the change.
3. **More-expensive changes** require justification:
   - Was the resource intentional? (new module, extra worker, larger EBS volume) → document in the PR description and bump `--max-delta` for the merge.
   - Did Terraform pick up an unexpected resource? → check the Infracost JSON for the actual diff items, often a stale state file.
4. **Override path** — pass `--max-delta` higher in the workflow input or temporarily edit `.github/workflows/ci-deployment.yml`. Only do this when the bigger spend is approved; never disable the gate as a shortcut.

---

## Scheduling cap

The `scheduler` Terraform module runs the AWS k3s pair only between **10:00 and 21:00 America/Sao_Paulo** by default — roughly 11h/day, ~45% uptime. With the default instance types this caps the EC2 bill at ~$24.59/month.

To suspend scheduling (always-on for a window):

```bash
make terraform-disable-schedule    # sets enable_scheduling = false
make terraform-enable-schedule     # restores the daily window
```

`terraform plan` for either of these will trip the Infracost gate (large delta) — the gate is doing its job. Either bump the threshold for that PR or do the schedule change locally with `terraform apply` after CI plan-only review.

---

## Account-level alerts (runtime guardrails)

The Infracost gate only sees *planned* changes; it cannot catch a spot price spike, a forgotten resource, or an externally-exposed bucket. The [`finops`](../../infra/aws/modules/finops) module adds free guardrails that watch the running account, all delivered through one SNS topic (`hl-cost-alerts`):

| Alert | Fires when | Default |
|---|---|---|
| AWS Budget `hl-monthly-cost` | spend ≥ 80% / 100% of budget, or forecast ≥ 100% | `monthly_budget_usd = 30` |
| Cost Anomaly Detection | a service's anomalous cost ≥ threshold | `anomaly_impact_threshold_usd = 10` |
| CloudWatch billing alarm | `EstimatedCharges` > threshold | `billing_alarm_usd = 35` |
| GuardDuty / Access Analyzer | a security finding is raised | — |

**Setup (one-time):** set `alert_email` (a plain, non-secret variable — it is an alert destination, not a credential) and apply. AWS then sends a confirmation email; **click the link** or the SNS subscription stays `PendingConfirmation` and nothing is delivered:

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn "$(cd infra/aws && terraform output -raw cost_alerts_topic_arn)" \
  --query 'Subscriptions[].SubscriptionArn'
# "PendingConfirmation" => the email link was not clicked yet
```

Verify the rest:

```bash
aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text)"
aws ce get-anomaly-monitors
aws accessanalyzer list-analyzers
```

When a budget/anomaly alert fires, work the same triage as the Infracost gate above; an Access Analyzer finding means a bucket or role is reachable from outside the account — treat as a security incident ([`../runbooks/on-call.md`](../runbooks/on-call.md)).

---

## Related

- [`cost-and-scheduling.md`](cost-and-scheduling.md) — steady-state cost breakdown
- [`../architecture/aws-infrastructure.md`](../architecture/aws-infrastructure.md) — module layout (incl. `scheduler`, `audit`)
- [`../runbooks/on-call.md`](../runbooks/on-call.md) — references the gate as a CI-failure trigger
