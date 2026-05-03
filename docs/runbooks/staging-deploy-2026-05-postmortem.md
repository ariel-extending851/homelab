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

**Permanent fix (TODO):** add an `instance_requirements` block to the fleet config to floor on memory (e.g. ≥ 2 GiB), or pin to non-spot for staging.

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

### 5. ArgoCD `apps-root` won't sync without the SSH cred secret

`k8s/gitops/apps-root.yaml` uses `repoURL: git@github.com:...` (SSH URL). The cluster needs the SSH deploy key in a Kubernetes secret named `argocd-repo-server-ssh` in the `argocd` namespace, plus that secret has to be mounted into the `argocd-repo-server` Deployment.

**Symptom after a fresh deploy:** `kubectl -n argocd get application` shows `Sync = Unknown`, with status condition `error creating SSH agent: "SSH agent requested but SSH_AUTH_SOCK not-specified"`.

**Setup steps:**

1. Generate (or reuse) a GitHub deploy key for the `homelab` repo with read-only access.
2. Create the Kubernetes secret:

   ```bash
   kubectl -n argocd create secret generic argocd-repo-server-ssh \
     --from-file=sshPrivateKey=/path/to/deploy_key \
     --type=Opaque
   ```

3. Patch `argocd-repo-server` Deployment to mount it (template at `k8s/gitops/sops/argocd-repo-server-patch.yaml:81/166`).

**Permanent fix (TODO):** turn this into an Ansible role task or a SOPS-encrypted secret committed to the repo and applied during `bootstrap_apps`.

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

## Permanent fixes still owed

These are TODO commits, separate PRs:

- [ ] `argocd-repo-server-ssh` secret bootstrap (Gotcha #5)
- [ ] `lifecycle { ignore_changes = [spot_options[0]…] }` (Gotcha #4)
- [ ] Staging-aware `ANSIBLE_AWS_SSM_BUCKET_NAME` default (Gotcha #1)
- [ ] `force_destroy = true` on staging S3 buckets (Gotcha #6)
- [ ] `session-manager-plugin` in devcontainer setup (Gotcha #2)
- [ ] `instance_requirements` floor on fleet memory (Gotcha #3)
