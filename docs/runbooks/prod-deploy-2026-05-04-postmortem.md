# Prod Deploy Postmortem — 2026-05-04

> **Owner:** @ariel-extending851
> **Status:** Cluster live on `t3.medium`; 4 follow-up PRs (#47, #48, #49, #50) shipped; one pending (Lambda auto-stop scheduler is broken on spot fleet).
> **Audience:** anyone running the next `gh workflow run ci-deployment.yml` deploy or troubleshooting the deploy pipeline.

---

## TL;DR

The first end-to-end CI prod deploy of the homelab on 2026-05-04 surfaced **8 land-mines** in the deploy path. **6 had code-level fixes** shipped same-day (PRs #47 through #50). **1 was operator-side** (terraform workspace pointed at `staging` while prod state lived in `default`). **1 is still open** (Lambda auto-stop never worked because spot fleet refuses `StopInstances`).

The deploy still succeeded: prod cluster is live at `54.205.176.133` on a `t3.medium` server (post the t3-medium pin in PR #49). The post-deploy baseline matches canary 3 — 8/13 apps Healthy, 3 separate-sprint crashloops (kyverno × 4, falco × 2, adguard × 1).

---

## Timeline (UTC)

| Time | Event | Run / commit |
|---|---|---|
| 17:59 | Old staging cluster orphaned from earlier dispatches (server `3.81.28.209`, agent `3.236.172.22`) | n/a |
| 19:30 | Audit-then-fix discovery: workflow expected `kubeconfig_content` Terraform output that never existed; would never have worked for k3s + Tailscale + SSM | n/a |
| 19:45 | Branch `fix/ci-deployment-honest-scope-2026-05-04` opened | PR #47 |
| 20:25 | PR #47 merged: workflow stripped to `terraform-apply` only (operator owns ansible/post-deploy) | `711a8d8` |
| 21:14 | Re-dispatch failed: `terraform-plan-prod` job tried to post a commit comment with `contents: read` (403 `Resource not accessible by integration`) | run `25343992373` |
| 21:50 | PR #48 merged: drop the broken commit-comment step; reviewer reads plan via the `terraform-plan-prod-logs` artifact | `c98b993`-1 |
| 22:14 | First successful end-to-end CI deploy: prod EC2 created via OIDC + production-approval Environment | run `25345449965` |
| 22:25 | First operator handoff (`make ansible-deploy`): playbook reported `ok=2 changed=0` on `localhost`, all plays "skipped: no hosts matched" — terraform inventory script returned empty | `/tmp/prod-ansible-deploy.log` |
| 22:30 | Root cause: local `terraform` CLI was on `staging` workspace (from earlier destroy); inventory script reads `terraform output -raw k3s_server_instance_id` from whichever workspace is selected | n/a |
| 22:35 | `terraform workspace select default` + re-run `make ansible-deploy`: cluster came up on **`t3.small`** server (`i-0e63c1df05c61804f`) — not the documented `t3.medium` | `/tmp/prod-ansible-deploy-2.log` |
| 22:40 | Root cause: `aws_ec2_fleet.k3s_server` override list `[t3.small, t3a.small, t3.medium]` + `price-capacity-optimized` allocation strategy = AWS picks the cheapest pool, ignoring the launch template's `instance_type = var.server_instance_type` | n/a |
| 23:00 | PR #49 merged: server fleet overrides pinned to `[t3.medium, t3a.medium]` only. Agent unchanged | `c98b993` |
| 23:18 | Re-dispatch with PR #49 included: `terraform-plan-prod` succeeded, `terraform-apply` reported success — but the live fleet still had old overrides | run `25348806949` |
| 23:33 | Root cause: `terraform apply plan.tfplan` exited 1 (`Cannot apply incomplete plan`); the `terraform apply ... \| tee apply.log` pipeline returned 0 because `tee` masked the real exit code; "Operator Handoff Notice" step ran anyway and posted success | apply log line |
| 23:35 | Underlying cause: `terraform-plan-prod` had AccessDenied on `s3:GetBucketPolicy` (`homelab-ssm-transfer-bucket`, `homelab-audit-trail`) and `guardduty:GetDetector`. Refresh failures marked the plan binary "incomplete." | run `25348806949` plan log |
| 23:39 | Operator terminated `i-0e63c1df05c61804f` to force the fleet to relaunch under the supposedly-updated overrides | aws cli |
| 23:40 | Fleet relaunched as **`t3.small` again** because the new overrides were never applied (silent failure above) | n/a |
| 23:50 | Operator ran `terraform apply -auto-approve` LOCALLY from the `default` workspace. Apply succeeded: fleet overrides updated to `[t3.medium, t3a.medium]`, but the 6 expected `aws_s3_bucket.velero_backups` etc. resources did not get created (state drift remains) | local terraform log |
| 23:52 | Operator terminated the new t3.small (`i-019906175a950c67a`); fleet relaunched as **`t3.medium`** (`i-0a3eae821c7fb9c4f`) | aws cli |
| 23:55 | `make ansible-deploy` failed immediately: SSM `TargetNotConnected` for the OLD instance ID. Terraform output still pointed to the just-terminated instance because `data.aws_instances.k3s_server` was not refreshed by `terraform refresh` (data sources need `terraform apply -refresh-only -auto-approve`) | `/tmp/prod-ansible-deploy-3.log` |
| 23:58 | `terraform apply -refresh-only -auto-approve`: outputs now reflect new server (`i-0a3eae821c7fb9c4f` @ `54.205.176.133`) | local |
| 00:30 | `make ansible-deploy` succeeded: PLAY RECAP `k3s-server: ok=117 changed=21 unreachable=1 failed=0`. The single `unreachable` was the late "wait for argocd convergence" task timing out on apps that were never going to be Healthy (the documented separate-sprint crashloops) — non-fatal | `/tmp/prod-ansible-deploy-4.log` |
| 00:35 | Smoke + E2E: same baseline failures as canary 3 (3 separate-sprint crashloops + 4 "0/0 expected 0" smoke-test reporting bug). Cluster officially in canary-3 parity | `/tmp/prod-smoke-test.log`, `/tmp/prod-e2e.log` |
| 00:39 | PR #50 merged: `set -o pipefail` on apply step + replace plan role inline policy with managed `ReadOnlyAccess`. Closes the silent-failure class of bug | `a36c0e0` |
| 00:40 | Lambda auto-stop should have fired at 00:00 UTC (= 21:00 BRT). Tried to manual-stop the EC2s for the night: `UnsupportedOperation: You can't stop the Spot Instance ... it is in a fleet, which does not support stop` | aws cli |

---

## Issue catalog

### #1 — Workflow expected a Terraform output that never existed for k3s + Tailscale + SSM

**Symptom:** `Export Kubeconfig` step at line 116/654 of `ci-deployment.yml` ran `terraform output -raw kubeconfig_content > /tmp/k3s-homelab-kubeconfig-staging.yaml`. No such output existed in `infra/aws/outputs.tf` (only `kubeconfig_command` — an `scp` command STRING, not the YAML).

**Root cause:** the workflow was authored with an EKS-style mental model (cluster API reachable from any runner; kubeconfig as a Terraform output). The reality is k3s on EC2 + Tailscale + Ansible-driven kubeconfig:

1. The k3s API listens only on the server's Tailscale CGNAT IP (`100.x.y.z`). A stock GitHub-hosted runner cannot reach it without a long-lived `TS_AUTH_KEY` secret. On a public repo, that secret is a tailnet-pivot risk.
2. Ansible's `community.aws.aws_ssm` connection plugin needs IAM permissions (`ssm:StartSession`, S3 transfer bucket access) intentionally out of scope for the apply role's permissions boundary.
3. The kubeconfig is generated by Ansible (slurp from the server, rewrite the API endpoint to the Tailscale IP). It cannot exist at `terraform apply` time — k3s is installed by Ansible next.

**Fix (PR #47, `711a8d8`):** stripped the workflow to `terraform-apply` only. After CI succeeds, the operator runs `make ansible-deploy && make smoke-test && make test-e2e-post-deploy` from a workstation already on the tailnet. Documented in [`docs/operations/terraform.md`](../operations/terraform.md#ci-vs-operator-responsibilities).

**Net diff:** −962 / +98 lines (removed 11 jobs that depended on cluster reachability or SSM).

---

### #2 — `terraform-plan-prod` cannot post commit comments with `contents: read`

**Symptom:** plan succeeded but the `Post Plan Summary on Commit` step failed with `403 Resource not accessible by integration`. The whole job failed; downstream jobs never ran.

**Root cause:** `repos.createCommitComment` requires `contents: write`, but the job only granted `contents: read` and `pull-requests: write` (the latter doesn't cover commit comments).

**Fix (PR #48, `c98b993`-1):** dropped the step entirely. The plan is preserved in the workflow artifact `terraform-plan-prod-logs` (`plan.txt`); reviewers download from the run page before approving. Avoids granting `contents: write` to a public-repo workflow.

**Net diff:** −20 / +4 lines.

---

### #3 — Spot fleet `price-capacity-optimized` downsized server to `t3.small`

**Symptom:** `aws ec2 describe-instances` showed `hl-k3s-server` came up as `t3.small` (2 GiB RAM), not the documented `t3.medium`.

**Root cause:** `infra/aws/modules/compute/main.tf:238-253` declared `aws_ec2_fleet.k3s_server` overrides as `[t3.small, t3a.small, t3.medium]` with `allocation_strategy = "price-capacity-optimized"`. AWS always picks the cheapest pool with capacity, ignoring `var.server_instance_type` from the launch template.

Same mechanism as gotcha #3 in the 2026-05-03 staging postmortem (originally `t3.micro` was in the list and caused 1 GiB hosts that OOM'd ArgoCD). The override list was floored at `t3.small` then but `t3.medium` was never enforced as the floor for the *server*.

**Why it matters in practice:** `t3.small` runs the control plane (etcd + kube-apiserver + ArgoCD repo-server CMP sidecar). ArgoCD reconcile of `homelab-apps-root` + kustomize manifest generation sustained ~1.6 GiB on canary 1; spikes during repo-server CMP startup push it close to 2 GiB → OOMKill territory. The recurring k3d CMP-sidecar flake on PRs #43/#45/#47 has the same shape; on prod `t3.small` it would become a deployment race, not just a CI flake.

**Fix (PR #49, `c98b993`):** server fleet overrides pinned to `[t3.medium, t3a.medium]`. AMD diversity preserved for spot capacity flexibility. Agent fleet unchanged (`[t3.small, t3a.small, t3.medium]` — workers run kubelet + small DaemonSets, comfortable at 2 GiB).

**Verification post-fix:** server `i-0a3eae821c7fb9c4f` reported `t3.medium`. `kubectl top node` showed server at **55% memory (2141Mi / 3900Mi)** vs **76% (1466Mi / 1900Mi)** on `t3.small` — 1.8 GiB headroom for ArgoCD spikes. `argocd-repo-server` 0 restarts.

**Net diff:** −12 / +14 lines (most was the comment block update).

---

### #4 — `terraform apply ... | tee apply.log` masked apply failures

**Symptom:** the workflow reported `Apply Terraform` job as "success" and printed the operator-handoff notice, but the actual `terraform apply plan.tfplan` exited with `Error: Cannot apply incomplete plan`. The fleet override change was never applied.

**Root cause:** the workflow step did not set `-o pipefail`. The pipeline `terraform apply ... | tee apply.log` returns whatever `tee` returned (always 0). `terraform`'s exit code never propagated. The downstream "Operator Handoff Notice" ran anyway. Future operators trust the green check; the silent-failure mode is worse than a noisy one.

**Fix (PR #50, `a36c0e0`):** added `set -o pipefail` to the step:

```yaml
run: |
  set -o pipefail
  terraform apply -lock=true plan.tfplan 2>&1 | tee apply.log
```

**Net diff (combined with #5):** −67 / +30 lines.

---

### #5 — Plan role missed `s3:GetBucketPolicy` and `guardduty:GetDetector`

**Symptom:** `terraform-plan-prod` plan output showed expected resource diffs but also accumulated AccessDenied errors during refresh:

- `s3:GetBucketPolicy` on `homelab-ssm-transfer-bucket`
- `s3:GetBucketPolicy` on `homelab-audit-trail`
- `guardduty:GetDetector`

Terraform marked the plan binary "incomplete" (combined with #4, this resulted in the silent apply skip).

**Root cause:** the `github-actions-terraform-plan` role's enumerated inline policy listed `s3:GetBucketTagging`, `s3:GetBucketEncryption`, `s3:ListBucket`, etc., but not `s3:GetBucketPolicy`. Same for GuardDuty. This same shape was always going to recur with each new resource type added to `infra/aws/` — incremental tightening creating its own failure mode. PRs #41 / #43 / #45 had analogous shape on the apply role.

**Fix (PR #50, `a36c0e0`):** replaced the enumerated inline policy with the AWS managed `arn:aws:iam::aws:policy/ReadOnlyAccess`. The plan role is read-only by definition; the worst case of broader scope is "reads more than it strictly needs," not privilege escalation. The privilege-escalation surface lives on the apply role, which keeps its tight enumerated set + permissions boundary unchanged.

**Trade-off rationale:**

| Role | Posture | Reasoning |
|---|---|---|
| `github-actions-terraform-plan` | Managed-broad (`ReadOnlyAccess`) | Read-only role; no escalation surface. Enumerated-tight cost = recurring incidents per new resource type. |
| `github-actions-terraform-apply` | Enumerated-tight + permissions boundary | Mutating role; every new permission is a real attack-surface decision. |

---

### #6 — Local terraform CLI on `staging` workspace blocked first ansible-deploy

**Symptom:** first `make ansible-deploy` after CI deploy reported all plays "skipping: no hosts matched"; final `PLAY RECAP` showed only `localhost: ok=2 changed=0`.

**Root cause:** `ansible/terraform_inventory_aws.py` shells out to `terraform output -raw k3s_server_instance_id` from the locally-selected workspace. The operator had run `terraform workspace select staging` earlier in the day to destroy the staging cluster, and never switched back. State for `staging` was empty (just destroyed); state for `default` (the prod CI workspace) had the fresh EC2s.

**Fix (operator-side, no code change):** documented in [`docs/operations/terraform.md`](../operations/terraform.md#ci-vs-operator-responsibilities). Run before any operator-side ansible:

```bash
cd infra/aws && terraform workspace select default
```

**Long-term:** the inventory script could be smarter (auto-detect workspace from a hint, or warn loudly when the active workspace's state is empty). Out of scope for this incident.

---

### #7 — `terraform refresh` does not refresh data sources

**Symptom:** after manually terminating a t3.small server to force fleet relaunch as t3.medium, `terraform refresh` ran cleanly but `terraform output -raw k3s_server_instance_id` still returned the old (terminated) instance ID. `make ansible-deploy` then SSM'd into the dead instance and got `TargetNotConnected`.

**Root cause:** Terraform's behavior. `terraform refresh` updates **resource** state from AWS but does not re-evaluate **data sources** (`data.aws_instances.k3s_server`). The output, computed from the data source's stored value, kept returning the cached ID.

**Fix:** use `terraform apply -refresh-only -auto-approve` instead. This re-evaluates data sources and rewrites outputs in state. After running it, the output reflected the new server (`i-0a3eae821c7fb9c4f`).

**For the runbook**: any time a fleet relaunches an EC2 (manual termination OR spot interruption), the local terraform state's view of the instance ID is stale until `apply -refresh-only` runs.

---

### #8 — Lambda auto-stop scheduler is broken on spot fleet (still open)

**Symptom:** the Lambda function `hl-ec2-scheduler` fires at 00:00 UTC daily (= 21:00 BRT) per its EventBridge cron. Lambda invocation logs show successful invocations. But EC2 instances stay running.

**Manual repro:**

```bash
aws ec2 stop-instances --instance-ids i-0a3eae821c7fb9c4f --region us-east-1
# error: UnsupportedOperation: You can't stop the Spot Instance 'i-...'
# because it is in a fleet, which does not support stop.
```

**Root cause:** the scheduler module (`infra/aws/modules/scheduler/lambda_src/lambda_function.py`) calls `ec2.stop_instances(InstanceIds=...)`. Spot instances managed by an EC2 Fleet refuse `StopInstances` — the fleet's `instance_interruption_behavior = "stop"` only governs what AWS does on *spot interruption*, not user-initiated stop. This was true for the entire history of the homelab; the auto-stop has never worked as documented.

**Cost impact:** the documented "$24.59/month with scheduling" assumed a 45 % uptime. With the scheduler broken, real cost is "$45.55/month 24/7" — about $20/month higher than advertised. (For a few-day window this is negligible; for a multi-month run, this matters.)

**Fix options (TODO, separate sprint):**

| Option | Effect | Complexity |
|---|---|---|
| Switch lambda to `aws_ec2_fleet.modify_fleet(target_capacity_specification.total_target_capacity = 0)` | Fleet drains to zero on stop, scales back to 1 on start | Low — single API call swap. Validate that fleet doesn't terminate the instance (it does — `terminate_instances = true` is set). EBS gets destroyed; cluster state lives in S3 + git. Acceptable for cattle-not-pets. |
| Replace fleet-managed spot with `aws_spot_instance_request` (persistent) | Stop works on persistent spot requests | Medium — touches the launch lifecycle and recovery on spot interruption. Removes fleet's auto-replace-on-interruption. |
| Drop scheduling entirely, accept 24/7 cost | Cost goes from "$24.59/month" to "$45.55/month" | Trivial — delete the scheduler module. Update `estimated_monthly_cost_usd` output. |

Recommendation pending: option 1 if the cattle-not-pets posture is a hard rule; option 3 if the operational simplicity wins.

---

## Open follow-ups (carried into next session)

| # | Item | Notes |
|---|---|---|
| 1 | Lambda auto-stop fix | See issue #8 above. Do *not* trust the `manual_stop_command` output until this lands. |
| 2 | Velero buckets not created | `aws_s3_bucket.velero_backups` and friends were in the local plan as "6 to add" but the local apply did not create them (state still shows them missing; `aws s3 ls \| grep velero` returns nothing). Re-dispatch `ci-deployment.yml` once #1 is fixed; the next CI plan should run cleanly with the new ReadOnlyAccess and the apply will create them. |
| 3 | Three documented separate-sprint crashloops | `falco`, `kyverno`, `adguard`. Tracked as separate cleanup work; not deploy regressions. |
| 4 | `staging.tfvars:23` `server_instance_type = "t3.small"` is now documentation-only | Fleet override list bypasses the launch-template `instance_type`, so this var is a no-op. Either document or remove. Filed as low-priority. |
| 5 | Smoke-test reports `0/0 expected 0` as `✗` | Apparent bug in `bin/smoke_test.py`: when an app legitimately runs 0 replicas (DaemonSets evaluated as Deployments, etc.), the test prints a cross instead of a check. Causes false-negative test failures. Tracked as a smoke-test bug, not a deploy regression. |
| 6 | `k3d GitOps Convergence` flake on PRs #43/#45/#47 | Same CMP sidecar startup race we hypothesised would also bite prod on `t3.small`. Now that prod is `t3.medium`, the race surface is smaller in production but remains in the k3d test (k3d cluster is small). Track separately if it keeps recurring. |

---

## What worked well

- **Scope-honest CI redesign (PR #47).** Removing 11 jobs that could never have worked on a public-repo + Tailscale-only architecture saved several days of trying to make a fundamentally wrong design work. The audit-then-fix decision tree is documented in `docs/operations/terraform.md` "CI vs operator responsibilities."
- **Per-PR Pipeline Gate as the only required check.** Every fix landed today went through the same gate: open PR → CI green → squash-merge → re-dispatch. Branch protection only required the aggregate `Pipeline Gate`, so the recurring `k3d GitOps Convergence` flake never blocked a merge.
- **Auto-mode + explicit-confirmation gates.** Auto-mode handled the routine work (creating PRs, opening branches, monitoring CI, parsing logs). Every action that mutated shared state (force-push, merge, dispatch, terminate) paused for explicit confirmation. The hook system stopped at least three near-mistakes (mass S3 audit-log delete, prod dispatch without auth, terraform destroy with `-auto-approve`).
- **Background watch + monitor pattern.** Long-running jobs (CI watch, ansible deploy, terraform apply) ran in the background; specific events (PLAY transitions, run conclusion, fleet relaunch type) surfaced as notifications. Avoided context-window waste from polling.
- **Plan mode for the t3.medium decision.** The user's mid-stream question "why is server t3.small? best way to fix? same in staging?" surfaced enough complexity (root cause, fleet semantics, staging side-effects, rollout sequence, blast radius) that a structured plan was worth more than an immediate edit.

## What did not work well

- **Successive-fix loop without a wide audit.** PRs #38, #39, #41, #43, #45 were all incremental tightenings of the same OIDC apply role; each fix surfaced the next gap. Same shape recurred today on the plan role. The fix in PR #50 (managed `ReadOnlyAccess`) is the structural answer to that loop. Apply role still uses enumerated-tight + boundary, but only because that role's escalation surface is real.
- **Silent CI failures.** The `tee` mask + missing `pipefail` (#4) cost about two iterations to detect. The fix is trivial; the cost was the time it took to notice the bug existed at all.
- **Stale data-source state after manual termination.** Two iterations of "ansible-deploy fails because terraform output points at dead instance" before realizing `terraform refresh` is the wrong command for data sources. Now documented (#7).
- **Workspace mismatch.** Half an hour debugging "no hosts matched" before noticing the workspace toggle. Now documented (#6) and the inventory script could probably be smarter.

---

## Cross-references

- [`docs/operations/terraform.md`](../operations/terraform.md) — CI vs operator responsibility split (added in PR #47).
- [`docs/runbooks/staging-deploy-2026-05-postmortem.md`](staging-deploy-2026-05-postmortem.md) — earlier postmortem of the staging-canary path, including gotchas #1-6 and the spot-fleet-instance-type-substitution behavior that bit again here.
- [`infra/aws/modules/compute/main.tf:238-253`](../../infra/aws/modules/compute/main.tf) — current server fleet override list.
- [`infra/aws-oidc/main.tf`](../../infra/aws-oidc/main.tf) — the plan role (managed ReadOnlyAccess) and the apply role (enumerated + boundary).
- [`.github/workflows/ci-deployment.yml`](../../.github/workflows/ci-deployment.yml) — the scope-honest CI workflow (PR #47) plus the pipefail fix (PR #50).
- Logs (ephemeral, on operator workstation): `/tmp/prod-ansible-deploy-{2,3,4}.log`, `/tmp/prod-smoke-test.log`, `/tmp/prod-e2e.log`.
- CI runs: [`25343992373`](https://github.com/ariel-extending851/homelab/actions/runs/25343992373) (failed at #2), [`25345449965`](https://github.com/ariel-extending851/homelab/actions/runs/25345449965) (first success), [`25348806949`](https://github.com/ariel-extending851/homelab/actions/runs/25348806949) (silent failure that surfaced #4 + #5).
