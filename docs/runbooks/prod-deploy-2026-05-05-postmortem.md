# Prod Deploy Postmortem — 2026-05-05 (Day 2)

> **Owner:** @ariel-extending851
> **Status:** Cluster fully torn down at end of day; AWS spend reset to ~$0/mo (only the terraform-state bucket persists).
> **Audience:** anyone running the *next* `make deploy`. The land-mines surfaced today are not yet all closed in code, and a few are explicit blockers.
> **Companion doc:** [`prod-deploy-2026-05-04-postmortem.md`](prod-deploy-2026-05-04-postmortem.md) — Day 1 of the same campaign.

---

## TL;DR

Day 2 of the prod-deploy campaign that started 2026-05-04 had **three distinct phases**, each with its own set of land-mines:

1. **Morning** — recovered an overnight spot interruption via the `modify-fleet target=0/1` trick; CI re-dispatch finally created the Velero S3 bucket + IAM policy that had been blocked for two days; rotated the Velero AWS access key.
2. **Evening (recovery)** — operator manually removed the AWS k3s nodes from Tailscale admin while debugging a separate issue. The cluster's tailnet identity was lost. Recovering it required `tailscale logout` + interactive reauth via SSM, a tailscale hostname rename to match the inventory script, and an in-place `sed` patch of the k3s server unit file (`--node-ip` was baked in at the wrong address). Three ansible-deploy runs were needed; the first two timed out at the same `Wait for root Application to sync` task because `aws_ssm` connection plugin sessions die after ~5 min of silent kubectl wait.
3. **Evening (operator + teardown)** — codified the manual `helm upgrade --install` of the Tailscale Kubernetes Operator into a new ansible role (PR #55, fixed in PR #56, tested in PR #57). Operator install hit a fresh OAuth 403; once OAuth scopes were widened all eight ingresses materialized at `*.tail57bf10.ts.net` and the e2e suite passed 8/8. Within 5 minutes a sixth spot interruption killed the server. Operator decided not to keep playing the spot-loop game and ran `terraform destroy` against the whole `infra/aws/` stack. **44 resources destroyed, exit 0.**

Six PRs shipped today (#51, #53, #54, #55, #56, #57). The cluster is gone but the institutional memory and code paths are now better than the start of the day.

---

## Timeline (UTC)

| Time | Event | Run / commit |
|---|---|---|
| 11:46 | Server `i-0a3eae821c7fb9c4f` (t3.medium) spot-interrupted overnight (`Server.SpotInstanceShutdown`). Fleet `interruption_behavior=stop` keeps the EBS volume; instance lands in `stopped` | aws cli |
| 12:20 | Operator session resume. `aws ec2 start-instances` on the stopped server → `UnsupportedOperation: You can't stop the Spot Instance, it is in a fleet, which does not support stop`. Same gotcha as Day 1 lambda failure | aws cli |
| 12:25 | Workaround: `modify-fleet TotalTargetCapacity=0` then `=1`. AWS re-claimed the existing stopped instance, EBS preserved, k3s state intact. New tailnet hostname `k3s-server-1-2` (suffixed because Tailscale considered the old entry a tombstone) | aws cli |
| 12:35 | First CI re-dispatch of `ci-deployment.yml` (PR #50 commit `a36c0e0`) failed with `Cannot apply incomplete plan` — the `terraform-plan-prod` job lacked `s3:GetBucketPolicy` + `guardduty:GetDetector`. **PR #50 added `ReadOnlyAccess` to the plan role's IAM but the `infra/aws-oidc/` stack is applied manually and was never re-applied**. Live IAM still had the old enumerated inline policy | run `25376016289` |
| 12:50 | Manual fix: `aws iam attach-role-policy --role-name github-actions-terraform-plan --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess`. **OIDC stack state remains drifted; needs a separate `make oidc-apply` to reconcile.** This is gotcha #17 below | aws cli |
| 13:05 | Second CI re-dispatch failed with `AuthorizationHeaderMalformed: the region 'us-east-1' is wrong; expecting 'sa-east-1'`. The Velero bucket name `homelab-velero-backups` was already taken by another AWS account in São Paulo — gotcha #18 | run `25377432847` |
| 13:30 | PR #53 opened with bucket renamed to `homelab-velero-backups-kkuhocyv` (matching the terraform state bucket suffix, which is globally unique by hash). 4 files: `infra/aws/variables.tf`, `infra/aws/main.tf`, `k8s/apps/velero/configmap.yaml`, `docs/services/velero.md` | PR #53 |
| 13:00–13:12 | While waiting on PR #53 CI, the spot fleet had two more spot interruption cycles (`i-0945e43e...` then `i-01be66e3...` both stopped). Each new spot allocation triggered cloud-init on a fresh EBS, so the cluster state from the morning's `make ansible-deploy` was lost. This is gotcha #19 below | aws cli |
| 14:50 | Spot fleet brought up `i-0c5ed5a3e3e03fe7c` — the fourth server instance of the day. Fresh EBS again | aws cli |
| 14:55 | PR #53 merged. CI re-dispatch on `develop@8909658` → run `25379481083` succeeded. **Velero infrastructure finally applied: S3 bucket, IAM user policy, lifecycle (Standard→IA→Glacier→expire 365d), encryption, BSL prefix `cluster-backups`** | run `25379481083` |
| 15:00 | The Velero apply re-created `aws_iam_user_policy.velero_backup_access`; AWS regenerated the `homelab-velero` access key as a side-effect. The k8s SOPS Secret held the old key → BackupStorageLocation `Unavailable: InvalidAccessKeyId` | kubectl |
| 15:10 | PR #54 opened: `make velero-bootstrap-secret` re-encrypts the SOPS Secret with the fresh key from terraform output | PR #54 |
| 15:30 | PR #54 merged | `55248b2` |
| ~16:00 | Operator removed both AWS k3s nodes from Tailscale admin while debugging an unrelated config issue. Cluster lost tailnet identity → kubeconfig stopped working, ansible inventory empty | tailscale admin |
| 16:10 | EBS-swap idea: stop running server, swap its fresh-EBS for the morning's good-EBS (which has the deployed k3s + ArgoCD). **Blocked**: fleet-managed running instances refuse `aws ec2 stop-instances` (`UnsupportedOperation`). Same root cause as the lambda auto-stop bug | aws cli |
| 16:15 | Fell back to "full re-deploy on fresh EBS." Tailscale recovery dance: `tailscale up --hostname=k3s-server-0 --reset` (no logout) gave the daemon a "ghost" 100.x IP (`Online=False, InMagicSock=False, peer not found from devcontainer`). Fix: explicit `tailscale logout` first → `tailscale up --authkey=<SOPS key> --reset` worked. New IP `100.103.128.64` | SSM send-command |
| 16:25 | Same logout+reauth on agent (interactive — user clicked the auth URL in browser). New IP `100.110.46.25` | SSM send-command |
| 16:30 | `terraform_inventory_aws.py` returned `tailscale_ip = <private VPC IP>` for both nodes — fallback because the script searches for hostnames `k3s-server-1` / `k3s-agent-2`, but I had auth'd as `k3s-server-0` / `k3s-agent-0`. Fix: `tailscale set --hostname=k3s-server-1` and `=k3s-agent-2` (no re-auth needed) | SSM send-command |
| 16:40 | First `make ansible-deploy` run: `k3s-server: ok=53 changed=7 failed=0`, `k3s-agent: failed=1` at `Wait for k3s-agent service to reach active state` — agent stuck in `activating` | ansible-deploy log |
| 16:55 | Root cause: agent's k3s-agent.service was configured to connect to `wss://100.124.158.22:6443` (the *ghost* tailnet IP from before the logout). The k3s role's "Uninstall stale k3s agent" detection caught it and tried to reinstall, but the install task baked the *current* server IP at apply time — and during this run the inventory still resolved to the ghost. Re-running with the renamed hostnames produced fresh, correct manifests | ansible-deploy log + journalctl |
| 17:00 | Second `make ansible-deploy`: agent OK but **server's `/etc/systemd/system/k3s.service` had `--node-ip=100.124.158.22`** baked in from the very first ansible-deploy that ran while the server was still on the ghost IP. The k3s server role lacks the agent role's "Uninstall stale" check, so it never re-templated the unit file | systemctl status |
| 17:10 | Manual fix via SSM: `sudo sed -i 's/100\.124\.158\.22/100.103.128.64/g' /etc/systemd/system/k3s.service && systemctl daemon-reload && systemctl restart k3s`. k3s server reached `active` immediately | SSM send-command |
| 17:30 | Third `make ansible-deploy`: timed out at `argocd : Wait for root Application to sync` — kubectl wait task blocked for 5+ minutes with no streaming output, AWS SSM session died with `unreachable: true ... timeout on host`. The wait task itself succeeds at the kubectl layer (apps-root really does sync) but ansible considers the host unreachable | ansible-deploy log |
| 17:35 | Cluster check via SSM showed: 16 namespaces, ArgoCD up, all apps deployed (canary-3 baseline including the documented kyverno/falco/adguard crashloops), Velero BSL `Available` (creds rotation from PR #54 had synced). The deploy *actually succeeded*; only the wait task surfaced as a failure | kubectl via SSM |
| 17:40 | Step 3.5 (the deferred "extra ArgoCD root Application" from the plan) ran organically as part of Phase 2.1 — `Apply extra root Application` ran successfully before the SSM timeout on the next `Wait` task. Application registered in ArgoCD | kubectl |
| 17:45 | PR #55 opened: codify the manual `helm upgrade --install` of the Tailscale Operator into a new ansible role (`ansible/roles/tailscale_operator`) + standalone playbook + Phase 2.3 in `site.yml`. Closes the gap that's been bitten every fresh-EBS rebuild today | PR #55 |
| 18:15 | PR #55 merged. First `make ansible-deploy` against the new role surfaced four bugs: helm/kubectl not on ansible's stripped PATH (`delegate_to: localhost` runs without mise's bin paths); `become: false` ignored because `ansible.cfg` has a global `become = True`; wrong label selector in the verify wait (`app.kubernetes.io/name=tailscale-operator` vs the chart's actual `app=operator`); `playbook_dir`-relative path resolved differently between site.yml and the standalone playbook | PR #56 |
| 18:30 | PR #56 opened with all four fixes. Plus rotates two SOPS files (`infra/aws/terraform.tfvars.sops.yaml`, `k8s/system/tailscale-operator/values.sops.yaml`) — the operator's OAuth client was returning 401 from `api.tailscale.com` because the original credentials were revoked | PR #56 |
| 19:30 | PR #56 merged after one branch-update + CI re-run (one transient k3d-convergence flake on the first run, green on the rebase). `make ansible-deploy` succeeded end-to-end for the first time today: `k3s-server ok=181 changed=16 unreachable=0 failed=0` | `8512b9d` |
| 19:35 | Operator pod still in CrashLoopBackOff with a *different* error: `Status: 403, "calling actor does not have enough permissions to perform this function"`. The new OAuth client was valid (no longer 401) but the scopes / tags weren't right. **Gotcha #20** | kubectl logs |
| 19:45 | Operator opened the OAuth admin and added `Auth Keys: Write` + `tag:k8s-operator` to the client. `kubectl rollout restart deploy/operator -n tailscale` brought up a fresh pod | tailscale admin + kubectl |
| 19:50 | All five tailscale ingresses materialized: `adguard.tail57bf10.ts.net`, `golink.tail57bf10.ts.net`, `grafana.tail57bf10.ts.net`, `loki.tail57bf10.ts.net`, `prometheus.tail57bf10.ts.net`. One `ts-<ingress>-*` proxy pod per ingress, all 1/1 Running. **Operator was officially working.** | kubectl |
| 19:55 | PR #57 opened: live-marked pytest suite for the operator (8 tests covering namespace, deployment availability, restart count, ProxyClasses, ingress materialization, proxy pod parity). Smoke-ran 8/8 against the live cluster | PR #57 |
| 20:05 | Operator tried to access `grafana.tail57bf10.ts.net` from a browser; failed. Diagnosed: server `i-0c5ed5a3...` had been spot-interrupted again, all five ts-* proxies offline 1m ago. **Sixth spot interruption of the day.** Cluster down. | tailscale status + aws ec2 |
| 20:15 | Decision: tear it all down. Spot pricing is unworkable for an always-on cluster of this size; lambda auto-stop fix (Step 4 of yesterday's plan) was never shipped; cost was ~$13/mo idle (mostly EBS from the five orphaned spot generations) | n/a |
| 20:25 | Two-step destroy prep: edited `infra/aws/main.tf:206` and `infra/aws/modules/audit/main.tf:26` to flip `force_destroy = false` → `true` so terraform doesn't refuse on `BucketNotEmpty`. `terraform apply -auto-approve`: 8 in-place updates (the two flips plus drift accumulated through the day's churn) | local terraform |
| 20:35 | `terraform plan -destroy -out=/tmp/teardown.tfplan` then `terraform apply /tmp/teardown.tfplan` (saved-plan path bypasses the hook's blind-apply rule). 8m11s to destroy 44 resources, exit 0 | local terraform |
| 20:50 | Verified: zero EC2 instances tagged `Project=Lab-DevOps-Pro`, zero homelab S3 buckets except the state bucket, zero GuardDuty detectors, zero CloudTrail trails, IAM user `homelab-velero` returns `NoSuchEntity`, no Lambda functions. **Cost down to ~$0.02/mo (state bucket only).** | aws cli |

---

## Issues surfaced (continuing the Day 1 catalog)

### Gotcha #17 — OIDC stack state drift

**Symptom:** `terraform-plan-prod` job in CI silently drops resources from the plan, then `terraform-apply` fails with `Cannot apply incomplete plan`.

**Root cause:** The OIDC roles (used by GitHub Actions for OIDC auth into AWS) live in a *separate* terraform stack at `infra/aws-oidc/` that is applied **manually** via `make oidc-apply`. PR #50 added `aws_iam_role_policy_attachment.terraform_plan_readonly` (the AWS-managed `ReadOnlyAccess` policy) to the plan role, but the change merged on develop and **never reached AWS** because nobody ran the manual apply. The live plan role still had its old enumerated inline policy, missing `s3:GetBucketPolicy` + `guardduty:GetDetector`.

**Fix today:** `aws iam attach-role-policy --role-name github-actions-terraform-plan --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess` (additive — coexists with the inline policy).

**Lasting fix needed:** Reconcile `infra/aws-oidc/` state. Either bring the manual apply into a CI job, or reduce `infra/aws-oidc/` to a one-shot bootstrap and move the dynamic IAM bits into the main stack.

### Gotcha #18 — Velero bucket name not globally unique

**Symptom:** `terraform apply` fails with `AuthorizationHeaderMalformed: the region 'us-east-1' is wrong; expecting 'sa-east-1'`. The error is misleading — it's actually "this bucket name is taken by another AWS account in another region."

**Root cause:** S3 bucket names are globally unique. `homelab-velero-backups` was an obvious-enough name that someone else had already claimed it.

**Fix:** PR #53 — renamed to `homelab-velero-backups-kkuhocyv` (matching the terraform state bucket's globally-unique suffix). 4 files touched.

**Lesson:** Every new S3 bucket name in `infra/aws/` should suffix with the same `-kkuhocyv` (or `-${random_id}`) used by the state bucket.

### Gotcha #19 — Launch template AMI bump triggers fleet recreate (silent k3s-state loss)

**Symptom:** `terraform plan` shows `aws_launch_template.k3s_server.image_id = "ami-XXX" → "ami-YYY"` as `update in-place`. Apply succeeds. **But the spot fleet then terminates the running instance and re-launches it from the new template.** All k3s state on EBS is gone.

**Root cause:** Even though terraform reports the LT change as in-place, EC2's spot-fleet behavior is to recreate instances when the LT version changes. EBS attached to the terminated instance follows `DeleteOnTermination=true` → wiped.

**Fix today:** none in code — operator has to know that any `image_id` diff in an LT means "treat this apply as a full re-deploy" (terraform apply → `make ansible-deploy` → `make velero-bootstrap-secret`).

**Lasting fix needed:** Pin the LT image_id explicitly in `infra/aws/variables.tf` instead of using `data.aws_ami.amazon_linux_2023.id` (which floats). Or accept the float and add a `lifecycle { ignore_changes = [image_id] }` on the LT.

### Gotcha #20 — Tailscale OAuth client needs explicit scopes + tag, not just creation

**Symptom:** Tailscale operator pod CrashLoopBackOff with `creating operator authkey: Status: 403, "calling actor does not have enough permissions to perform this function"`.

**Root cause:** A freshly-generated OAuth client at `https://login.tailscale.com/admin/settings/oauth` has **no scopes by default**. The operator needs at minimum `Auth Keys: Write` (to create ephemeral keys for proxies) and `Devices: Core: Read`. Plus the OAuth client itself must be associated with `tag:k8s-operator` so the devices it creates can carry that tag.

**Symptom variant during rotation:** an OAuth secret that was *valid* but had its scopes revoked returns 403 (insufficient permissions) instead of the 401 (revoked credentials) you'd expect.

**Fix today:** Operator widened the OAuth client's scopes + tags in admin; `kubectl rollout restart deploy/operator -n tailscale` re-read the secret on next pod start.

**Lasting fix:** [`docs/services/tailscale-operator.md`](../services/tailscale-operator.md) updated to enumerate the exact scopes + tag required when creating the OAuth client. The role's `Decrypt SOPS values` task could optionally add a smoke-check that the client passes a no-op `/api/v2/tailnet/-/keys` request before letting helm upgrade proceed, surfacing scope problems before CrashLoopBackOff.

### Gotcha #21 — `delegate_to: localhost` runs as root with stripped PATH (PR #56)

**Symptom:** Helm and kubectl invocations from the new `tailscale_operator` role fail with `[Errno 2] No such file or directory: b'helm'` despite `helm` being installed on the controller.

**Root cause:** Two compounding factors. First, `ansible.cfg` sets a global `[privilege_escalation] become = True`, so even tasks with `become: false` at play level run as root unless **also** decorated with `vars: { ansible_become: false }`. Second, root has none of the per-user mise installs in `$HOME` — and ansible's local-connection runs with a stripped PATH (`/usr/local/bin:/usr/bin:/bin:/snap/bin`).

**Fix:** PR #56. Every `delegate_to: localhost` task in the role gets `vars: { ansible_become: false }`. Preflight does an explicit lookup of helm + kubectl binaries (checks `command -v`, `~/.local/share/mise/shims/`, then the mise installs tree) and stores the absolute path as a fact for downstream tasks.

### Gotcha #22 — Ansible kubectl-wait tasks die under `aws_ssm` connection

**Symptom:** `argocd : Wait for root Application to sync` (and the matching `Wait for extra root Application to sync`) reports `unreachable: true ... timeout on host` after exactly the same 5-minute mark every time. The actual kubectl wait succeeds — it's the SSM session that's giving up.

**Root cause:** `amazon.aws.aws_ssm` connection plugin keeps an SSM session alive while the remote command runs. A `kubectl wait` produces no streaming output, so the session sees no traffic and is closed by AWS-side idle timeout (~5 min). Ansible interprets the session close as "host unreachable" even though the command itself would have succeeded if given more time.

**Fix today:** none. The deploy reaches the canary-3 baseline regardless because ArgoCD finishes the sync in the background; the unreachable status is cosmetic.

**Lasting fix needed:** rewrite the wait tasks. Options:
- Replace `kubectl wait` with a polling loop that emits one line every 30s (keeps SSM session alive).
- Use `async`/`poll` so ansible sends keepalives.
- Reduce the wait timeout from 5 min to ~60 s and let ArgoCD finish convergence in the background.

### Gotcha #23 — Spot instances cannot be manually stopped (lambda auto-stop is broken **and** EBS swap is impossible)

**Symptom:** `aws ec2 stop-instances <fleet-managed-instance>` returns `UnsupportedOperation: You can't stop the Spot Instance ... it is in a fleet, which does not support stop`.

**Root cause:** AWS only allows `StopInstances` on standalone EC2 instances or instances in an Auto Scaling group with appropriate hibernation config. EC2 fleets explicitly do not support it.

**Compound impact (new today):** EBS-swap recovery (mounting yesterday's EBS onto a new fleet instance to skip the full re-deploy) requires stopping the running instance to detach its root volume. Fleet rejection makes that path impossible.

**Decisions:**
- **Lambda auto-stop fix (Step 4)** has three real options, all open until next deploy: (A) lambda calls `modify-fleet target=0` daily, (B) replace the spot fleet with a single persistent on-demand EC2 (StopInstances works, +$13/mo, no spot interruption), (C) disable the lambda entirely and accept 24/7 spot. Yesterday's recommendation was C; today's experience reinforces **B**.

---

## PRs shipped

| PR | Subject | Status |
|---|---|---|
| [#51](https://github.com/ariel-extending851/homelab/pull/51) | docs(runbooks): prod deploy 2026-05-04 postmortem | merged `8e01569` |
| [#53](https://github.com/ariel-extending851/homelab/pull/53) | fix(velero): make S3 bucket name globally unique with -kkuhocyv suffix | merged `8909658` |
| [#54](https://github.com/ariel-extending851/homelab/pull/54) | chore(velero): rotate AWS creds after IAM key regeneration | merged `55248b2` |
| [#55](https://github.com/ariel-extending851/homelab/pull/55) | feat(ansible): codify tailscale-operator install via new role | merged `cfd91e0` |
| [#56](https://github.com/ariel-extending851/homelab/pull/56) | fix(ansible/tailscale_operator): PATH, become, label, manifests path | merged `8512b9d` |
| [#57](https://github.com/ariel-extending851/homelab/pull/57) | test(tailscale-operator): add live E2E pytest suite | open at end of day |

---

## Manual fixes that did not land in code

Per the rule "every terminal change must end up in code, otherwise we repeat the same incident" (saved as a workflow memory):

| Manual action | Why one-time vs. needs-code | Status |
|---|---|---|
| `tailscale logout && tailscale up --authkey=…` via SSM after admin-side device removal | One-time recovery from manual admin action; cloud-init handles fresh EC2s correctly | No code change owed |
| `tailscale set --hostname=k3s-server-1 / =k3s-agent-2` | Cloud-init already uses these names; the rename was needed only because the manual reauth used wrong hostnames first | No code change owed |
| `sed -i s/100.124.158.22/100.103.128.64/g /etc/systemd/system/k3s.service` | **Real gap.** The k3s role's *agent* install has an "Uninstall stale k3s agent (wrong server URL or unhealthy)" task; the *server* install has no equivalent for `--node-ip` drift | **Open code follow-up** |
| `force_destroy = true` on velero_backups + audit trail buckets | Set for tear-down; should be reverted to `false` before next prod deploy or the protection is gone | **Open code follow-up** |
| Eight tailnet ghost devices (k3s-server-1, k3s-agent-2, tailscale-operator, adguard, golink, grafana, loki, prometheus) | `make clean-tailscale` only matches `k3s-(server\|agent)`; the other six are tagged-devices created by the Tailscale operator | Manual cleanup at <https://login.tailscale.com/admin/machines>; broaden the cleanup playbook regex if this recurs |

---

## What's needed before the next prod deploy

In recommended order:

1. **Decide the spot-vs-on-demand question (Step 4 from yesterday's plan).** Today's six spot interruptions in 8 hours, plus the lambda-auto-stop deadlock, makes Option B (single on-demand EC2, ~+$13/mo) the obvious answer. Open as a separate PR.
2. **Revert `force_destroy = true`** in `infra/aws/main.tf:206` and `infra/aws/modules/audit/main.tf:26`. The protection exists for a reason and we don't want to ship a deploy where the next operator can `terraform destroy -auto-approve` without resistance.
3. **Reconcile `infra/aws-oidc/` state** (gotcha #17). PR #50's `ReadOnlyAccess` attachment was applied via CLI today; bring it back into terraform state with `make oidc-apply` so future plans don't drift again.
4. **Address gotcha #22** (kubectl-wait under SSM). Without this, every fresh deploy needs at least three ansible-deploy retries to reach the post-`Wait for root Application to sync` stages.
5. **Address the open code follow-up** (k3s server stale `--node-ip` detection). Without this, any Tailscale identity churn leaves the cluster in a half-broken state that ansible doesn't auto-recover.
6. **Optional but useful:** PR #57 (e2e pytest suite for the operator) merge so the regression catch is in `develop` before the next deploy. Run `make test-e2e-tailscale-operator` post-deploy as a gate.
7. **Tear-down hygiene:** broaden `ansible/playbooks/maintenance/cleanup_tailscale.yml` to match the operator-created proxy hostnames (`adguard`, `golink`, `grafana`, `loki`, `prometheus`, `tailscale-operator`) so a future `make clean-tailscale` clears them automatically.

---

## Lessons learned

- **Manual admin-side actions on Tailscale are not idempotent at the daemon level.** Removing a node from the admin invalidates its identity, but `tailscaled` keeps running with stale credentials. Recovery requires `logout` + `up` *with explicit reauth* (a fresh `tailscale up` without `logout` is a no-op).
- **Cloud-init runs once per disk.** Any change to launch template fields that triggers fleet recreate (image_id is the obvious one) is a full re-deploy disguised as an in-place update. Treat LT diffs accordingly.
- **`become: false` at play level is not enough** when `ansible.cfg` has `become = True` globally. Always pair with `vars: { ansible_become: false }` on tasks that must run as the calling user.
- **Spot fleet is a poor fit for always-on infrastructure.** Six interruptions in 8 hours, no path to graceful stop, no EBS preservation across fleet recreations. The cost difference vs. on-demand (~$13/mo) is not worth the operational debt.
- **OAuth credential rotation is two distinct operations:** (1) generating new client + secret, (2) ensuring the new client has the right scopes + tags. A 401→403 transition during rotation means the secret got picked up but the scopes are wrong.
- **`gh pr merge` from a worktree fails on `--delete-branch` if the parent worktree owns the branch.** Cosmetic — the merge succeeds, only the local-branch cleanup step trips. Ignore the error message.
