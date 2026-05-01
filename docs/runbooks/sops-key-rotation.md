# SOPS Age Key Rotation

The SOPS Age key (`SOPS_AGE_KEY` GitHub secret + local
`~/.config/sops/age/keys.txt`) decrypts every secret in this repo
(Tailscale auth keys, k3s tokens, Velero credentials, etc.). It is a
single-credential blast radius: anyone who exfiltrates it can decrypt
everything in `*.sops.*` files.

This runbook covers two scenarios:

1. **Routine rotation** — annually, no incident
2. **Emergency rotation** — credential is suspected compromised

## Find the current recipients

Each SOPS-encrypted file has its recipients listed in the `sops:` block
at the bottom:

```bash
grep -A2 "age:" infra/aws/terraform.tfvars.sops.yaml | head
```

Every recipient public key listed is one identity that can decrypt the
file. The repo is configured to encrypt to all recipients via
`.sops.yaml` at repo root.

## Routine rotation

Rotate yearly even without incident — keys age, machines change,
laptops die.

```bash
# 1. Generate the new key locally.
age-keygen > ~/.config/sops/age/keys.txt.new
NEW_PUB=$(grep '^# public key:' ~/.config/sops/age/keys.txt.new | awk '{print $4}')

# 2. Add the new public key to .sops.yaml — keep the old recipient
#    listed for now so existing files stay decryptable mid-rotation.
$EDITOR .sops.yaml

# 3. Re-encrypt every SOPS-managed file with the updated recipient set.
#    This works because we still have the old private key locally.
for f in $(git ls-files | grep '\.sops\.'); do
  sops updatekeys --yes "$f"
done

# 4. Update the GitHub secret SOPS_AGE_KEY with the NEW private key.
#    Settings → Secrets → SOPS_AGE_KEY → Update.

# 5. Confirm CI can decrypt with the new key (push a no-op commit and
#    watch the trivy-image-scan job — its setup decrypts the secrets).

# 6. Once CI is green, swap files locally to make the new key primary
#    and remove the old one.
mv ~/.config/sops/age/keys.txt ~/.config/sops/age/keys.txt.old.$(date +%Y%m%d)
mv ~/.config/sops/age/keys.txt.new ~/.config/sops/age/keys.txt

# 7. Edit .sops.yaml again — REMOVE the old recipient.
$EDITOR .sops.yaml
for f in $(git ls-files | grep '\.sops\.'); do
  sops updatekeys --yes "$f"
done

# 8. Commit + push the .sops.yaml change and the re-encrypted files in
#    a single PR titled "rotate SOPS Age key (annual)".

# 9. Archive the old private key somewhere offline (printed paper in a
#    safe, encrypted USB stick — your call). Do NOT keep it on the
#    workstation; that defeats the rotation.
```

Verification: `sops -d infra/aws/terraform.tfvars.sops.yaml | head -5`
should succeed; if you removed the old key in step 7 it will fail
without the new key in `~/.config/sops/age/keys.txt`.

## Emergency rotation (suspected compromise)

If you have any reason to think the key has leaked (laptop stolen, key
file mistakenly committed, GitHub secret exposed in workflow logs):

1. **Burn it now, ask questions later.** Don't wait to confirm.
2. Generate a new Age key (step 1 above).
3. **Generate new values for every secret encrypted with the old key.**
   This is the part most rotation guides skip — the actual *content*
   has been exposed, not just the wrapper. At minimum:
   - Tailscale auth key → revoke at <https://login.tailscale.com/admin/settings/keys>
   - k3s cluster token → regenerate via emergency_recovery playbook
   - Velero AWS access key → rotate via `aws iam create-access-key` +
     update `infra/aws/main.tf` Velero IAM user reference
   - Any GitHub deploy keys for ArgoCD secondary repos
4. Re-encrypt with the new Age key + new secret values (steps 3-7 of
   routine rotation).
5. Force a deploy so the new secrets land everywhere
   (`gh workflow run ci-deployment.yml`).
6. Open a security note in the repo (private gist or just a commit
   message) recording: when, why, what was rotated, what wasn't.

## What NOT to do

- **Don't re-use the old public recipient** on the assumption that "the
  private key is gone now". The encrypted ciphertext still exists in
  git history. Anyone who later obtains the old private key can decrypt
  every commit ≤ rotation point. That's fine for routine rotation
  (we're not pretending to revoke history) but is a bad default reflex.
- **Don't keep the old private key on the workstation "just in case".**
  That makes the rotation theatrical. Archive it offline or destroy it.
- **Don't rotate without re-running the deploy.** The cluster's running
  pods still have the old secret values mounted. They keep working
  until restarted, but a new pod scheduled later will pull the new
  values and behave inconsistently. A planned deploy resolves this.
