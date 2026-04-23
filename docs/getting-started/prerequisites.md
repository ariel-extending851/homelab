# Prerequisites

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Tools, credentials, and keys you need on your workstation before running `make deploy`.

---

## Tooling (use mise)

Everything is pinned in [`.mise.toml`](../../.mise.toml). One-time setup:

```bash
# Install mise (if you don't have it)
curl https://mise.jdx.dev/install.sh | sh

# In the repo directory, install all tools
mise install
make setup-ci-deps-all   # verifies + installs anything missing (pytest-cov, boto3, etc.)
```

This installs: `terraform`, `tflint`, `sops`, `age`, `kubectl`, `kustomize`, `kubeconform`, `ansible-core`, `ansible-lint`, `molecule`, `pytest`, `bats`, `localstack`, `awscli`, `jq`, `conftest`, plus a few helpers.

If you don't use mise, you'll need at minimum: `terraform >= 1.5`, `ansible >= 2.16`, `aws` CLI, `kubectl`, `sops`, `age`. Versions in `.mise.toml` are the source of truth.

---

## AWS Credentials

```bash
aws configure --profile homelab
# Region: us-east-1
# Output: json

aws sts get-caller-identity --profile homelab    # verify
```

`mise` auto-sets `AWS_PROFILE=homelab` inside the repo. Outside the repo, export it manually.

The IAM user/role needs at least:
- EC2 (full)
- IAM (CreateRole, AttachRolePolicy, PassRole)
- S3 (full on the two buckets — `homelab-terraform-state-kkuhocyv` and `homelab-ssm-transfer-bucket`)
- Lambda + EventBridge (for the scheduler module)
- SSM (for break-glass node access)

---

## SSH Key for AWS

```bash
ssh-keygen -t ed25519 -f ~/.ssh/homelab-aws -C "homelab-ec2" -N ""
ls ~/.ssh/homelab-aws*    # should show the keypair
```

The public key is loaded into `infra/aws/terraform.tfvars.sops.yaml` (SOPS-encrypted). Terraform injects it into the EC2 user-data so `ec2-user` can SSH in.

---

## SOPS Age Key

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt

# Public key — must match what's in .sops.yaml:
grep 'public key:' ~/.config/sops/age/keys.txt
# expect: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja
```

> **Mismatched public key?** Either restore your existing key from backup, or re-encrypt every SOPS file in the repo (advanced — see [`../operations/sops-setup.md#rotate-the-age-key`](../operations/sops-setup.md#rotate-the-age-key)).

`mise` auto-sets `SOPS_AGE_KEY_FILE` inside the repo. Backup that key file to two media; loss = permanent inability to decrypt.

Full procedure: [`../operations/sops-setup.md`](../operations/sops-setup.md).

---

## GitHub Deploy Key (for ArgoCD)

ArgoCD pulls from the repo using a **read-only** SSH deploy key.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/homelab-deploy-key -C "argocd@homelab" -N ""
cat ~/.ssh/homelab-deploy-key.pub
# paste the public key at:
# https://github.com/ariel-extending851/homelab/settings/keys/new
# title: ArgoCD Deploy Key (Read-Only)
# Allow write access: ❌ unchecked

# Test
ssh -T -i ~/.ssh/homelab-deploy-key git@github.com
# expect: "Hi ariel-extending851/homelab! You've successfully authenticated..."
```

The Ansible `argocd` role mounts this key into the cluster as a Secret. Detail: [`../architecture/gitops.md#repository-configuration`](../architecture/gitops.md#repository-configuration).

---

## Tailscale (free tier is fine)

You need a tailnet (free, <https://tailscale.com/start>). The Ansible `tailscale` role joins each node using an auth key delivered through SOPS.

For the auth key:
- <https://login.tailscale.com/admin/settings/keys>
- **Reusable:** Yes, **Ephemeral:** No, **Pre-approved:** Yes
- **Tags:** `tag:k8s-node` (recommended)

For the Tailscale operator OAuth (used by the cluster ingress):
- <https://login.tailscale.com/admin/settings/oauth>
- Scopes: `auth_keys`, `devices`

Both go into SOPS-encrypted secrets. Detail: [`../services/tailscale-operator.md`](../services/tailscale-operator.md).

---

## Python deps (Ansible Phase 2)

The ArgoCD bootstrap playbook needs the Python `kubernetes` library:

```bash
pip3 install kubernetes
python3 -c "import kubernetes; print('OK')"
```

And the Ansible collections:

```bash
ansible-galaxy collection install -r ansible/requirements.yml
ansible-galaxy collection list | grep -E "kubernetes|sops"
```

`mise install` covers most of this; the explicit pip + collection install is the belt-and-suspenders fallback.

---

## Verification Checklist

Before running `make deploy`, all of these should pass:

```bash
[ -f ~/.ssh/homelab-aws ]                                                  && echo OK || echo MISSING_SSH_KEY
[ -f ~/.ssh/homelab-deploy-key ]                                           && echo OK || echo MISSING_DEPLOY_KEY
[ -f ~/.config/sops/age/keys.txt ]                                         && echo OK || echo MISSING_AGE_KEY
aws sts get-caller-identity --profile homelab >/dev/null 2>&1              && echo OK || echo AWS_AUTH_FAILED
sops -d infra/aws/terraform.tfvars.sops.yaml | head -3 >/dev/null 2>&1     && echo OK || echo SOPS_DECRYPT_FAILED
ssh -T -i ~/.ssh/homelab-deploy-key git@github.com 2>&1 | grep authenticated && echo OK || echo GITHUB_AUTH_FAILED
mise install >/dev/null 2>&1                                               && echo OK || echo MISE_INSTALL_FAILED
python3 -c "import kubernetes" 2>/dev/null                                 && echo OK || echo PIP_MISSING_KUBERNETES
```

All `OK`? Run `make deploy`.

## Related

- **Deployment guide:** [`deployment.md`](deployment.md)
- **SOPS setup deep-dive:** [`../operations/sops-setup.md`](../operations/sops-setup.md)
- **ArgoCD bootstrap detail:** [`../operations/ansible.md#argocd-bootstrap-phase-2-detail`](../operations/ansible.md#argocd-bootstrap-phase-2-detail)
