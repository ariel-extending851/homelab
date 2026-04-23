# SOPS Setup

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

How to set up SOPS + age on a fresh workstation, encrypt the secrets the repo needs, and migrate the gatekeeper Wi-Fi credentials. The high-level model (what gets encrypted, how ArgoCD decrypts at sync time) is in [`../architecture/secrets-management.md`](../architecture/secrets-management.md).

---

## TL;DR

```bash
# 1. Install
brew install sops age              # macOS
sudo apt install age               # Linux (sops via mise — see below)

# 2. Generate the age key
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt

# 3. Confirm the public key matches what the repo expects
grep 'public key:' ~/.config/sops/age/keys.txt
# expect: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja

# 4. Wire up the env (mise does this automatically inside the repo)
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"

# 5. Decrypt to confirm
sops -d infra/aws/terraform.tfvars.sops.yaml | head -3
```

> **Public-key mismatch?** Either restore the existing key from your secure backup, or re-encrypt every file in the repo with your new public key (advanced). Day-to-day operation requires the key matching `age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja` because that's what's pinned in [`.sops.yaml`](../../.sops.yaml) and the ArgoCD `sops-age` Secret.

---

## Tool Installation

The repo pins `sops` and `age` in [`.mise.toml`](../../.mise.toml) — `mise install` brings them in alongside Terraform / Ansible / kubectl. If you prefer system packages:

```bash
# macOS
brew install sops age

# Linux (Ubuntu/Debian)
# sops not in apt; install from GitHub release:
curl -L -o /tmp/sops "https://github.com/getsops/sops/releases/download/v3.8.1/sops-v3.8.1.linux.amd64"
sudo install /tmp/sops /usr/local/bin/sops
sudo apt install age
```

Verify:
```bash
sops --version       # ≥ 3.8
age --version        # ≥ 1.1
```

---

## Generate the Age Key

The age key is a single text file holding both the private (top) and public (commented) parts.

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
```

> **Back this file up immediately.** Two media, two locations. Loss = permanent inability to decrypt.

Display the public key:
```bash
grep 'public key:' ~/.config/sops/age/keys.txt
# Example output:
# # public key: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja
```

---

## Environment

`mise` sets `SOPS_AGE_KEY_FILE` automatically inside this repo (configured in [`.mise.toml`](../../.mise.toml)). Outside the repo, or if you don't use mise, add to `~/.bashrc` or `~/.zshrc`:

```bash
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
```

Reload: `source ~/.bashrc`.

---

## Encrypt the Terraform Secrets

The Terraform root module needs three secrets in `infra/aws/terraform.tfvars.sops.yaml`:

```yaml
ssh_public_key: "ssh-ed25519 AAAA... homelab-aws"
k3s_token: "xY..." # openssl rand -base64 32
tailscale_auth_key: "tskey-auth-..."
```

**Recommended workflow** — let `.sops.yaml`'s catch-all rule auto-encrypt on save:

```bash
# Edit (in-memory decrypt, re-encrypt on save)
sops infra/aws/terraform.tfvars.sops.yaml
```

If creating from scratch (no encrypted file yet), encrypt explicitly:

```bash
sops --encrypt --in-place infra/aws/terraform.tfvars.sops.yaml
```

Confirm the encryption took:
```bash
head -5 infra/aws/terraform.tfvars.sops.yaml
# Each value should be ENC[AES256_GCM,data:...]
```

---

## Encrypt a Kubernetes Secret

The path-based rule in `.sops.yaml` matches `*secret*.yaml`. Workflow:

```bash
# Author the plaintext draft
cat > k8s/apps/myapp/secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: myapp
  namespace: myapp
type: Opaque
stringData:
  api_key: "redacted"
EOF

# Encrypt in place
sops --encrypt --in-place k8s/apps/myapp/secret.yaml

# Confirm
grep -E 'data|stringData' k8s/apps/myapp/secret.yaml
# fields should be ENC[...]
```

ArgoCD decrypts at sync time via the SOPS CMP plugin in `argocd-repo-server` (set up by the `argocd` Ansible role). See [`../architecture/secrets-management.md#how-argocd-decrypts-at-sync`](../architecture/secrets-management.md#how-argocd-decrypts-at-sync).

---

## Migrate Gatekeeper Wi-Fi Secrets

The gatekeeper role originally had `wifi_password` in `roles/gatekeeper/defaults/main.yml` as a test fallback. Production should use an encrypted group var instead.

### Steps

1. Create the router secret file from the example:
   ```bash
   cp ansible/group_vars/router.sops.yaml.example ansible/group_vars/router.sops.yml
   ```

2. Encrypt it in place:
   ```bash
   sops --encrypt --in-place ansible/group_vars/router.sops.yml
   ```

3. Edit safely (decrypt-on-open, re-encrypt-on-save):
   ```bash
   sops ansible/group_vars/router.sops.yml
   ```

4. Confirm Ansible can read inventory without exposing secrets:
   ```bash
   cd ansible
   ansible-inventory -i inventory/production.yml --graph
   ```

5. Run the gatekeeper playbook:
   ```bash
   make ansible-router
   ```

### Why this works

- `wifi_password` in `roles/gatekeeper/defaults/main.yml` remains as a non-secret fallback — useful for tests/Molecule
- Variable precedence puts `group_vars/router.sops.yml` above role defaults for hosts in the `router` group
- `.sops.yaml` rule for `ansible/group_vars/*.sops.yaml` encrypts only `wifi_password` and `wifi_guest_password` fields, not the whole file

---

## Common Operations

| Need | Command |
|---|---|
| View encrypted file | `sops -d <file>` |
| Edit encrypted file | `sops <file>` |
| Encrypt a fresh file | `sops --encrypt --in-place <file>` |
| Re-encrypt with new recipient set (post-`.sops.yaml` change) | `sops updatekeys <file>` |
| Re-encrypt every file matching the rules | `find . -name '*.sops.yaml' -exec sops updatekeys -y {} \;` |

---

## Rotate the Age Key

Non-trivial. Detailed procedure in [`../architecture/secrets-management.md#rotate-the-age-key`](../architecture/secrets-management.md#rotate-the-age-key). Summary:

1. `age-keygen -o ~/.config/sops/age/keys-new.txt`
2. Add the new public key to `.sops.yaml` alongside the old one
3. `find . -name '*.sops.yaml' -exec sops updatekeys -y {} \;` (now both keys can decrypt)
4. Verify decrypt with the new key
5. Remove the old public key from `.sops.yaml`, run `updatekeys` again
6. Update the cluster-side `sops-age` Secret (re-run `make ansible-deploy --tags=sops-key`)
7. Securely destroy the old private key

---

## Troubleshooting

### `no SOPS data found in file`
The file isn't encrypted. Run `sops --encrypt --in-place <file>` once.

### `could not decrypt data key with any master key`
`SOPS_AGE_KEY_FILE` not set, or pointing at the wrong key. Check:
```bash
echo $SOPS_AGE_KEY_FILE
grep 'public key:' "$SOPS_AGE_KEY_FILE"
```
If your public key doesn't match `age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja`, restore your backup.

### `age: no identity matched any recipient`
The file was encrypted with a different age key. Either find the original private key or re-encrypt the file with `sops --rotate --add-age $YOUR_PUBLIC_KEY <file>` (only works if you have access to one of the existing recipients).

### Terraform errors at `data.sops_file.secrets`
Run from the same shell that has `SOPS_AGE_KEY_FILE` set. Most often this happens when `terraform` is invoked from a CI runner or sub-shell that didn't inherit the env. Verify with `sops -d infra/aws/terraform.tfvars.sops.yaml | head -3` first.

### Pre-commit blocks a secret commit
The repo's pre-commit hook refuses to commit anything matched by `.sops.yaml` rules but not encrypted. Fix:
```bash
sops --encrypt --in-place <the file>
git add <the file>
git commit
```

---

## Related

- **High-level model + ArgoCD CMP:** [`../architecture/secrets-management.md`](../architecture/secrets-management.md)
- **Terraform usage:** [`terraform.md`](terraform.md)
- **Ansible bootstrap (installs the cluster-side `sops-age` Secret):** [`ansible.md`](ansible.md)
- **Why the SSM bucket is separate from the state bucket:** [`../architecture/aws-infrastructure.md#ssm-transfer-bucket`](../architecture/aws-infrastructure.md#ssm-transfer-bucket)
