# Cost Controls

> **Status:** Active · **Last reviewed:** 2026-05-01
> **Owner:** @ariel-extending851

Two layers of cost governance: the **Infracost gate** in CI (catches regressions in PR), and the **scheduling Lambda** that bounds runtime expense. Per-resource estimates and steady-state cost live in [`cost-and-scheduling.md`](cost-and-scheduling.md); this doc covers *the gate* and *what to do when it fires*.

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

## Related

- [`cost-and-scheduling.md`](cost-and-scheduling.md) — steady-state cost breakdown
- [`../architecture/aws-infrastructure.md`](../architecture/aws-infrastructure.md) — module layout (incl. `scheduler`, `audit`)
- [`../runbooks/on-call.md`](../runbooks/on-call.md) — references the gate as a CI-failure trigger
