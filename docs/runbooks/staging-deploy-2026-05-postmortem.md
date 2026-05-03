# Staging Deploy Postmortem — 2026-05-03

> **Owner:** @ariel-extending851
> **Status:** Closed; 4 fixes shipped in PR #27
> **Audience:** anyone running `make terraform-staging-apply` + `make ansible-deploy` from a fresh worktree

## TL;DR

A staging deploy from a fresh worktree on 2026-05-03 surfaced **6 land-mines** in the deploy path. 4 had code-level fixes (PR #27). 2 are operational gotchas you must know about. **Every fresh deployer hits these unless they read this page first.**

## The 4 fixes already merged (PR #27)

You don't need to do anything for these — they're in `develop`. Listed here so you recognize the symptom if you ever see it on a branch that pre-dates the fix.

| Fix commit | Symptom | Where |
|---|---|---|
| `0e55bb5` | `terraform plan` succeeds but EC2 user-data ships literal `ENC[…]` strings, breaking `tailscale up` and k3s agent registration | `infra/aws/terraform.tfvars.sops.yaml` had `ENC[ENC[…]]` (re-encrypted twice) on `ssh_public_key`, `k3s_token`, `tailscale_auth_key` |
| `d4837c2` | `terraform apply` 412 `invalid old hash` from Tailscale provider | `tailscale_acl.homelab_acl` resource overwriting a non-default live ACL |
| `b242e42` | `python3 bin/velero_bootstrap_secret.py` → `Invalid cross-device link` | hardcoded `dir='/tmp'` in tempfile when workspace was on a different filesystem |
| `56e36d8` | Ansible 15× retries `Could not find the requested service k3s-agent: host` then fails | `INSTALL_K3S_NAME=k3s-agent` made the installer create `k3s-k3s-agent.service` while role expected `k3s-agent.service` |

## Operational gotchas you MUST know before re-deploying

### 1. Staging needs an env override for SSM bucket name

`.mise.toml:111` defaults `ANSIBLE_AWS_SSM_BUCKET_NAME` to the production bucket. Staging uses a `-staging` suffix. Without override, every Ansible task fails immediately at `Gathering Facts` with **`HeadBucket … 404 Not Found`**.

**Workaround:** prepend the env var on every `make ansible-deploy` for staging:

```bash
ANSIBLE_AWS_SSM_BUCKET_NAME=homelab-ssm-transfer-bucket-staging make ansible-deploy
```

**Permanent fix (TODO):** make the default staging-aware (read from terraform output, or detect workspace).

### 2. `session-manager-plugin` is not in `.mise.toml`

The Ansible `aws_ssm` connection plugin requires AWS's `session-manager-plugin` binary. Devcontainers don't ship with it. **Symptom:** Ansible `Gathering Facts` fails with `Failed to find required executable "session-manager-plugin"`.

**Install once per devcontainer:**

```bash
curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o /tmp/sm.deb && sudo dpkg -i /tmp/sm.deb
```

**Permanent fix (TODO):** add to devcontainer `postCreateCommand` or to a `setup-ci-deps-*` Makefile target.

### 3. Spot fleet may substitute a smaller instance type

`staging.tfvars` requests `t3.small` for the server, but the spot fleet's `price-capacity-optimized` allocation can substitute **t3.micro** (1 GiB RAM) when that's cheapest. Verify with:

```bash
aws ec2 describe-instances --instance-ids <id> --query 'Reservations[].Instances[].InstanceType' --output text
```

**Why it matters:** ArgoCD on a t3.micro briefly hits load 8 during initial reconcile. It recovers, but SSM session-manager exec timeouts (default ~6 min) can fire on long-running `kubectl apply` tasks.

**If it bites you:**

- The Ansible `Apply ArgoCD manifest` task is the most exposed. If it `UNREACHABLE!`s, kill the task, then apply the manifest **directly via kubectl from the devcontainer** using the local kubeconfig at `/tmp/k3s-homelab-kubeconfig.yaml`:

  ```bash
  KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml \
    kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.13.2/manifests/install.yaml
  ```

- Bypass works because devcontainer reaches the k3s API directly over Tailscale; no SSM session involved.

**Permanent fix (applied):** dropped `t3.micro`/`t3a.micro` from the fleet `override` list in `infra/aws/modules/compute/main.tf` so the spot fleet can only substitute among `t3.small`/`t3a.small`/`t3.medium` (all ≥ 2 GiB). Chose this over `instance_requirements` to keep the AMI's x86_64 constraint enforced (an `instance_requirements` block could otherwise substitute Graviton `t4g.*` and silently break user-data).

### 4. `spot_options.instance_pools_to_use_count` drift forces fleet replacement

After the first `terraform-staging-apply`, AWS reports `instance_pools_to_use_count = 0` while the provider default is `1`. Next plan shows **"forces replacement"** for both fleets — destroying and recreating the EC2 instances.

**Don't apply blindly.** Read the plan diff. If both fleets show `must be replaced`, this is the cause.

**Permanent fix (TODO):** in `infra/aws/modules/compute/main.tf` lines 252 and 306, add:

```hcl
spot_options {
  allocation_strategy            = "price-capacity-optimized"
  instance_interruption_behavior = "stop"
}

lifecycle {
  ignore_changes = [spot_options[0].instance_pools_to_use_count]
}
```

### 5. ArgoCD `apps-root` won't sync without the SSH repo secret

`k8s/gitops/apps-root.yaml` uses `repoURL: git@github.com:...` (SSH URL). ArgoCD picks up repository credentials from a Secret labelled `argocd.argoproj.io/secret-type: repository`. In this repo that secret is **`homelab-repo-secret`**, created by `ansible/roles/argocd/tasks/configure_repo.yml`.

> **Note:** earlier versions of this runbook called the missing secret `argocd-repo-server-ssh`. That is **not** the right name — `argocd-repo-server-ssh` is just an `emptyDir` volume mounted at `/app/config/ssh` for known-hosts material (see `k8s/gitops/sops/argocd-repo-server-patch.yaml:81,166`). Creating a generic Secret with that name does **not** register a credential with ArgoCD.

**Real root cause on 2026-05-03:** `configure_repo.yml` reads `~/.ssh/homelab-deploy-key` from the control machine. When that file was absent on a fresh devcontainer, the create-secret task was silently skipped (no error), and `bootstrap_apps.yml` then applied `apps-root.yaml` with no repository credentials wired up.

**Symptom after a fresh deploy:** `kubectl -n argocd get application` shows `Sync = Unknown`, with status condition `error creating SSH agent: "SSH agent requested but SSH_AUTH_SOCK not-specified"`.

**Setup steps (one-time per operator):**

1. Generate the deploy key and register the public key as a read-only deploy key on the GitHub repo:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/homelab-deploy-key -C "argocd@homelab" -N ""
   cat ~/.ssh/homelab-deploy-key.pub   # paste at https://github.com/<owner>/homelab/settings/keys/new
   ssh -T -i ~/.ssh/homelab-deploy-key git@github.com   # confirm authenticated
   ```
2. Re-run `make ansible-deploy`. `configure_repo.yml` will create `homelab-repo-secret` automatically.

**Manual recovery (only if `apps-root` is already wedged):**

```bash
KEY=~/.ssh/homelab-deploy-key
KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml kubectl -n argocd apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: homelab-repo-secret
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: git
  url: git@github.com:ariel-extending851/homelab.git
  sshPrivateKey: |
$(sed 's/^/    /' "$KEY")
EOF
```

**Permanent fixes (PR pending — see Fase 0.1 of `prod-deploy` plan):**

- `configure_repo.yml`: replace silent skip with an explicit `fail` when the key file is missing (so the operator can't proceed without noticing).
- `bin/preflight.py`: add `git.deploy_key` check that fails before deploy starts if `~/.ssh/homelab-deploy-key` is absent.

### 6. Versioned S3 buckets break `terraform destroy`

CloudTrail / Velero backup buckets have S3 versioning enabled. `terraform destroy` fails with **`BucketNotEmpty`** because terraform doesn't recursively delete versions + delete-markers.

**Recovery:**

```bash
for BKT in homelab-audit-trail homelab-velero-backups-staging homelab-ssm-transfer-bucket-staging; do
  aws s3api list-object-versions --bucket "$BKT" --output json \
    --query '{Objects: Versions[].{Key: Key, VersionId: VersionId}}' > /tmp/v.json
  aws s3api delete-objects --bucket "$BKT" --delete file:///tmp/v.json || true
  aws s3api list-object-versions --bucket "$BKT" --output json \
    --query '{Objects: DeleteMarkers[].{Key: Key, VersionId: VersionId}}' > /tmp/m.json
  aws s3api delete-objects --bucket "$BKT" --delete file:///tmp/m.json || true
  aws s3api delete-bucket --bucket "$BKT" || true
done
mise exec -- terraform -chdir=infra/aws destroy -var-file=staging.tfvars -auto-approve
```

**Permanent fix (TODO):** add `force_destroy = true` to the audit-trail / velero-backups / ssm-transfer S3 bucket resources for staging only.

## Pre-deploy checklist (run before EVERY staging deploy)

```bash
# 1. Plugin check (devcontainer-local; install once)
which session-manager-plugin || \
  (curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" \
   -o /tmp/sm.deb && sudo dpkg -i /tmp/sm.deb)

# 2. SOPS sanity (catches the ENC[ENC[…]] bug)
mise exec -- sops -d infra/aws/terraform.tfvars.sops.yaml | \
  awk -F': ' '/^(ssh_public_key|k3s_token|tailscale_auth_key|tailscale_api_key):/ \
    {print $1": prefix="substr($2,1,4)" len="length($2)}'
# Expected prefixes: ssh-, … (random k3s base64), tske…, tske…
# If you see ENC[ as a prefix, you've hit the double-encrypt bug — see fix `0e55bb5`.

# 3. Tailnet sanity
sudo systemctl start tailscaled || sudo /usr/sbin/tailscaled \
  --state=/var/lib/tailscale/tailscaled.state \
  --socket=/var/run/tailscale/tailscaled.sock --port=41641 &
tailscale status | head

# 4. Preflight
python3 bin/preflight.py
# Expect: 0 fail. Warns are OK pre-deploy (no cluster yet, no SSM instances yet).
```

## The deploy

```bash
make terraform-staging-init     # workspace select
make terraform-staging-plan     # 5s; sanity-check 43 add / 0 destroy
make terraform-staging-apply    # ~5min; 42 resources (tailscale_acl resource is disabled)

# Note the env override — see Gotcha #1
ANSIBLE_AWS_SSM_BUCKET_NAME=homelab-ssm-transfer-bucket-staging make ansible-deploy
```

If `make ansible-deploy` hits `UNREACHABLE!` on the `Apply ArgoCD manifest` task, see Gotcha #3.

## Tear-down

```bash
mise exec -- terraform -chdir=infra/aws destroy -var-file=staging.tfvars -auto-approve
```

If you see `BucketNotEmpty`, see Gotcha #6.

## New gotchas surfaced during the 2026-05-03 canary re-deploy (post PR #28)

### 7. SOPS sidecar patch redefined upstream volumes (Fixed in PR #29)

`k8s/gitops/sops/argocd-repo-server-patch.yaml` declared 5 volumes (`argocd-repo-server-{tmp,ssh,tls,gpg-source,gpg-keys}`) as `emptyDir`, mounting them at the same paths upstream uses for its `tmp`, `ssh-known-hosts`, `argocd-repo-server-tls`, `gpg-keys`, `gpg-keyring` configMaps/secrets. Two failure modes:

- **Strategic-merge invalid spec** for `argocd-repo-server-tls` (upstream secret + patch emptyDir → "more than 1 volume type").
- **`ssh-known-hosts` shadowed** by the patch's emptyDir at `/app/config/ssh` — apps-root sync then failed with `unable to find any valid known_hosts file, set SSH_KNOWN_HOSTS env variable`.

Was masked on 2026-05-03 because the operator bypassed the patch step (Gotcha #3 workaround). Fix: keep only the SOPS-pipeline-owned volumes (`sops-age-key`, `custom-tools`, `cmp-plugin`, `cmp-tmp`) in the patch.

### 8. apps-root CRD ordering — `PrometheusRule` applied before its CRD

`k8s/apps/storage-latency/prometheusrule.yaml` declares `apiVersion: monitoring.coreos.com/v1` `PrometheusRule`, but the repo's Prometheus deployment (`k8s/apps/prometheus/`) is a plain `Deployment` — not prometheus-operator — so the `monitoring.coreos.com` CRD is never installed. ArgoCD `apps-root` then loops through 5 retries and gives up: `The Kubernetes API could not find monitoring.coreos.com/PrometheusRule for requested resource storage-latency/storage-latency`.

**Permanent fix (applied):** migrated the two alerts (`StorageLatencyDegraded`, `StorageLatencyMonitorStalled`) to plain Prometheus rules under the `storage-latency.rules` group inside `k8s/apps/prometheus/configmap.yaml` (same pattern the rest of the homelab alerts use). Deleted `k8s/apps/storage-latency/prometheusrule.yaml` and removed it from `k8s/apps/storage-latency/kustomization.yaml`. No prometheus-operator dependency, alerts preserved.

### 9. Cilium takeover bricks the cluster on first deploy

After PR #28+#29+#30 unblocked apps-root sync, the `homelab-apps-root` Application reached `Synced/Degraded/Succeeded` and started cascading children. **Cilium** (`k8s/apps/cilium/`) was the first to install — it tried to take over CNI from the existing flannel that k3s installed at bootstrap time. Result: networking broke mid-flight, both `kubectl` over Tailscale **and** SSM agent commands stopped responding (server EC2 still `running`, but ssm-agent stuck in `Pending`). The 2026-05-03 19:43 UTC canary cluster ended up unrecoverable from the devcontainer.

This is unrelated to the prod-deploy plan changes — those validated end-to-end before this. But the same takeover would happen on a fresh prod deploy unless `k8s/apps/cilium/` either:

- Replaces flannel atomically via the `--flannel-backend=none --disable-network-policy` k3s install flags **at cluster boot time** (Ansible role change), or
- Is removed from the apps-root pattern and Cilium is installed pre-cluster instead.

Same class of issue as #8 (apps-root assumes a clean dependency order that doesn't hold on first deploy). **TODO, separate PR**.

## Permanent fixes still owed

These are TODO commits, separate PRs:

- [x] `homelab-repo-secret` bootstrap hardening — fail loud + preflight check (Gotcha #5, PR #28)
- [x] SOPS sidecar patch — drop redundant volume overrides (Gotcha #7, PR #29)
- [x] apps-root CRD ordering — alerts migrated to plain Prometheus rules, no operator needed (Gotcha #8, PR #30)
- [x] Cilium takeover during apps-root sync bricks the cluster — Cilium app removed from apps-root in PR #31; re-enable via Ansible pre-cluster install when ready (Gotcha #9)
- [ ] `lifecycle { ignore_changes = [spot_options[0]…] }` (Gotcha #4)
- [ ] Staging-aware `ANSIBLE_AWS_SSM_BUCKET_NAME` default (Gotcha #1)
- [ ] `force_destroy = true` on staging S3 buckets (Gotcha #6)
- [ ] `session-manager-plugin` in devcontainer setup (Gotcha #2)
- [x] Fleet memory floor — dropped `t3.micro` from overrides (Gotcha #3)
