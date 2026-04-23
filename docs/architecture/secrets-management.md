# Secrets Management

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

All secrets in this repo are encrypted with [SOPS](https://github.com/getsops/sops) using [age](https://age-encryption.org/). The same age key encrypts both Terraform variables and Kubernetes Secrets, so a single recipient can operate the whole stack.

---

## Key Material

| Item | Value | Location |
|---|---|---|
| Age public key (recipient) | `age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja` | [`.sops.yaml`](../../.sops.yaml) |
| Age private key | (not in repo) | `~/.config/sops/age/keys.txt` |
| Env var (override) | `SOPS_AGE_KEY_FILE` | Set in [`.mise.toml`](../../.mise.toml) |

> **Backup the private key.** Loss = inability to decrypt anything. Recommended: keep an offline copy on at least two media (e.g., printed paper backup + USB drive in a safe).

---

## What Gets Encrypted

The encryption rules in [`.sops.yaml`](../../.sops.yaml) match by file path and field name:

| Path pattern | Fields encrypted | Used by |
|---|---|---|
| `ansible/group_vars/*.sops.yaml` | `wifi_password`, `wifi_guest_password` | gatekeeper (router) role |
| `*secret*.yaml` | `data`, `stringData`, `ssh_public_key`, `k3s_token`, `tailscale_*` | Kubernetes Secret manifests |
| `k8s/apps/*/secrets/*.yaml` | `data`, `stringData` | App-specific secret directories |
| `*.enc.yaml` | (whole file) | Generic encrypted env files |
| `*.sops.yaml` (catch-all) | tokens, secrets, passwords, keys, API keys, credentials (regex) | Terraform variables, ad-hoc files |

The catch-all rule (last in the file) is the most aggressive — match any field whose name contains `token`, `secret`, `password`, `key`, `api_key`, or `credential`. This is what protects `infra/aws/terraform.tfvars.sops.yaml`.

---

## Workflow

### Edit an encrypted file

```bash
sops k8s/apps/grafana/secret.yaml
```
Opens in `$EDITOR` decrypted in memory; re-encrypts on save.

### Encrypt a new file in place

```bash
sops -e -i k8s/apps/newapp/secret.yaml
```
Use this once to convert a plaintext draft. Pre-commit refuses to commit anything matched by the rules but not encrypted.

### Decrypt to stdout (debug only)

```bash
sops -d k8s/apps/grafana/secret.yaml
```
Don't pipe this to a file you intend to commit.

### Rotate the age key

This is non-trivial and not currently scripted. The procedure is:

1. Generate a new age key: `age-keygen -o ~/.config/sops/age/keys-new.txt`
2. Update every recipient line in [`.sops.yaml`](../../.sops.yaml) to include both keys
3. Run `sops updatekeys <file>` for every encrypted file in the repo
4. Confirm decrypt with the new key
5. Drop the old key from `.sops.yaml` and run `updatekeys` again
6. Securely destroy the old private key on every host that had it

---

## How ArgoCD Decrypts at Sync

ArgoCD uses a **CMP (Config Management Plugin)** to invoke SOPS during repo manifest generation. Specifically, `argocd-repo-server` is patched with:

- A sidecar mounting the age private key from a Kubernetes Secret
- `SOPS_AGE_KEY_FILE` set to that mount path
- A plugin definition that runs `kustomize build … | sops --input-type yaml --output-type yaml -d /dev/stdin` for matched manifests

The Ansible role [`ansible/roles/argocd`](../../ansible/roles/argocd) installs ArgoCD and applies the CMP patch. See [`../operations/sops-setup.md`](../operations/sops-setup.md) for the cluster-side setup procedure.

The Application manifest at [`k8s/gitops/apps-root.yaml`](../../k8s/gitops/apps-root.yaml) sets `ignoreDifferences` on Secret `data` so SOPS-decrypted values don't cause sync drift.

---

## How Terraform Decrypts at Plan/Apply

The root [`infra/aws/main.tf`](../../infra/aws/main.tf) uses the `carlpett/sops` provider:

```hcl
data "sops_file" "secrets" {
  source_file = "${path.module}/terraform.tfvars.sops.yaml"
}

locals {
  secrets = data.sops_file.secrets.data
}
```

Three secrets are loaded: `ssh_public_key`, `k3s_token`, `tailscale_auth_key`. They're injected into the compute module's user-data. With `localstack_test = "yes"` the data source is bypassed and mock values are substituted (no SOPS decryption attempted).

---

## CI

GitHub Actions cannot decrypt — it has no access to the age private key. CI workflows therefore:

- **Validate** SOPS-encrypted files exist where required (`make validate-sops-workflow`)
- **Plan** Terraform with `localstack_test=yes` so it doesn't need the SOPS data source
- **Reject** PRs containing plaintext secrets (pre-commit + a CI lint pass)

Anything that needs real secrets (`terraform apply`, deploy playbooks) runs from your machine where the age key is available.

---

## Where to Go Next

- **Cluster-side setup procedure:** [`../operations/sops-setup.md`](../operations/sops-setup.md)
- **Per-app secret patterns:** the relevant doc under [`../services/`](../services/)
- **Why the SSM bucket is separate from the state bucket:** [`aws-infrastructure.md`](aws-infrastructure.md#ssm-transfer-bucket)
