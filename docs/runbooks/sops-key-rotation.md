# Runbook: SOPS Age Key Rotation

| Field | Value |
|:--- |:--- |
| **Severity** | 🟡 Warning (routine) · 🔴 Critical (emergency) |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-05-12 |
| **Owner** | @ariel-extending851 |
| **Blast Radius** | Every `**/secret.yaml`, `infra/aws/terraform.tfvars.sops.yaml`, all Ansible SOPS group_vars; ArgoCD CMP cannot decrypt until cluster has the new key |
| **RPO Impact** | Zero if procedure is followed; live secrets are *not* re-issued unless emergency rotation requires it |

The SOPS age key (local `~/.config/sops/age/keys.txt` plus GitHub secret `SOPS_AGE_KEY`) decrypts every secret in this repo. It is a single-credential blast radius — anyone with the key can decrypt Tailscale auth, k3s tokens, Velero credentials, and every app `secret.yaml`. This runbook covers two scenarios:

1. **Routine rotation** — annual, no incident.
2. **Emergency rotation** — credential suspected compromised.

---

## 1. Preconditions

Run before any rotation. The procedure is reversible *only* if these hold.

| Check | Command | Expect |
|---|---|---|
| Current key decrypts | `sops -d infra/aws/terraform.tfvars.sops.yaml \| head -1` | Decrypted content |
| CI is green on `develop` | (GitHub PR list) | No failing checks |
| No in-flight deploy | `gh run list --workflow ci-deployment.yml --limit 1` | Last run completed |
| Backup of current key exists | `ls -la ~/.config/sops/age/keys.txt.backup-*` | At least one file |
| Operator can reach every node | `for n in k3s-server k3s-agent rasp-pi-03 rasp-pi-04; do ssh "$n.tail57bf10.ts.net" true; done` | All return 0 |

!!! warning "Rotate during a low-change window"
    A rotation mid-deploy can leave half the cluster decrypting with the old recipient and half with the new. Pick a quiet window and freeze merges to `develop` until the rotation completes.

---

## 2. Locate Current Recipients

Each SOPS-encrypted file declares its recipients in the `sops:` block at the bottom:

```bash
grep -A2 "age:" infra/aws/terraform.tfvars.sops.yaml | head
```

The repo is configured to encrypt to all recipients via the root [`.sops.yaml`](../../.sops.yaml). Every public key listed there can decrypt every matching file.

---

## 3. Routine Rotation (annual)

Rotate yearly even without incident — keys age, machines change, laptops die. ~30 min including verification.

```bash
# Step 1 — generate the new key locally
age-keygen > ~/.config/sops/age/keys.txt.new
NEW_PUB=$(grep '^# public key:' ~/.config/sops/age/keys.txt.new | awk '{print $4}')

# Step 2 — add the NEW recipient to .sops.yaml; KEEP the old one for the transition
$EDITOR .sops.yaml
# .sops.yaml now lists both <old_pub> and <new_pub>

# Step 3 — re-encrypt every SOPS-managed file with the updated recipient set.
# This works because the old private key is still primary on the workstation.
for f in $(git ls-files | grep '\.sops\.'); do
  sops updatekeys --yes "$f"
done

# Step 4 — update the GitHub secret SOPS_AGE_KEY with the NEW private key
# (Settings → Secrets and variables → Actions → SOPS_AGE_KEY → Update).

# Step 5 — confirm CI can decrypt with the new key.
# Push a no-op commit to a temp branch and watch the trivy-image-scan job
# (its setup decrypts secrets).
git commit --allow-empty -m "chore: trigger CI decrypt check (rotation N)"
gh run watch

# Step 6 — promote new key to primary locally
mv ~/.config/sops/age/keys.txt "~/.config/sops/age/keys.txt.backup-$(date +%Y%m%d)"
mv ~/.config/sops/age/keys.txt.new ~/.config/sops/age/keys.txt

# Step 7 — remove the OLD recipient from .sops.yaml and re-encrypt
$EDITOR .sops.yaml
# .sops.yaml now lists only <new_pub>
for f in $(git ls-files | grep '\.sops\.'); do
  sops updatekeys --yes "$f"
done

# Step 8 — single PR: ".sops.yaml + re-encrypted files"
git checkout -b rotate-sops-age-key-$(date +%Y)
git add .sops.yaml
git add $(git ls-files | grep '\.sops\.')
git commit -m "rotate SOPS age key (annual)"
git push -u origin HEAD
gh pr create --draft --title "rotate SOPS age key (annual)" \
  --body "Annual rotation per docs/runbooks/sops-key-rotation.md."

# Step 9 — archive old private key offline (paper safe / hardware token).
# Do NOT keep it on the workstation; that defeats the rotation.
```

---

## 4. Emergency Rotation (compromise suspected)

Triggered by: laptop stolen, key file mistakenly committed, GitHub secret exposed in workflow logs, or any reason to believe the private key has left controlled storage.

!!! danger "Burn it now, ask questions later."
    Confirmation costs time the attacker is also using. Proceed in parallel: rotate while the investigation runs.

The procedure differs from routine in two material ways:

1. **Every secret encrypted with the old key must also be re-issued.** Ciphertext exists in git history; the attacker has the *content*, not just the wrapper.
2. **A force-deploy follows** so the cluster picks up the new secret values before the next scheduled sync.

```bash
# Step 1 — Steps 1, 2, 3 of routine rotation (new key, update .sops.yaml, re-encrypt).

# Step 2 — Re-issue every secret value the old key could decrypt. AT MINIMUM:

# 2.1 Tailscale auth key — revoke at:
#     https://login.tailscale.com/admin/settings/keys
#     Generate a new one; place it in the SOPS file; re-encrypt.

# 2.2 k3s cluster token — regenerate via emergency_recovery role
make ansible-deploy --tags emergency_recovery

# 2.3 Velero AWS access key — rotate via IAM
aws iam create-access-key --user-name velero_backup_user
# Update infra/aws/terraform.tfvars.sops.yaml with the new key; old one becomes inactive
aws iam update-access-key --user-name velero_backup_user --access-key-id <OLD_ID> --status Inactive
# After 24 h of confirmed cluster operation:
aws iam delete-access-key --user-name velero_backup_user --access-key-id <OLD_ID>

# 2.4 Any GitHub deploy keys for ArgoCD secondary repos — rotate in GitHub UI;
#     update the corresponding SOPS-encrypted Secret manifest.

# 2.5 Any third-party API tokens referenced in **/secret.yaml — case-by-case.

# Step 3 — Routine rotation steps 4-8 (update GitHub secret, re-encrypt, promote
# locally, remove old recipient, commit the PR).

# Step 4 — Force-deploy so the cluster picks up the new secrets immediately.
gh workflow run ci-deployment.yml

# Step 5 — Open a security incident note recording: when, why, what was rotated,
# what wasn't (and the rationale), and the expected residual exposure window.
$EDITOR docs/security/audit-history.md
```

---

## 5. Verification Matrix

After either rotation, every row below must pass before the runbook is considered closed.

| Check | Command | Expect |
|---|---|---|
| New key decrypts canary | `sops -d infra/aws/terraform.tfvars.sops.yaml \| head -1` | Decrypted content |
| Old key no longer decrypts | `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt.backup-<date> sops -d <file>` | **Failure** (proves old recipient was removed) |
| CI green with new GitHub secret | `gh run list --workflow ci-validation.yml --limit 1` | `completed: success` |
| ArgoCD reconciles a SOPS-backed Secret | `kubectl rollout restart deploy/<known-secret-consumer> -n <ns>` then `kubectl rollout status` | Rollout completes; pod logs show fresh secret values |
| Velero still authenticates to S3 | `velero backup-location get` | Phase: Available |
| Tailscale auth still works on every node | `ssh <node>.tail57bf10.ts.net tailscale status` | All peers visible |

If any row fails, **rollback (§6) before proceeding.**

---

## 6. Rollback

The rotation is rollback-able only during a narrow window — between Step 2 (new recipient added) and Step 7 (old recipient removed). In that window, both keys decrypt; reverting `.sops.yaml` to the old-only recipient set is safe.

After Step 7, rollback requires the archived old private key (Step 9 of routine rotation). If that key has already been destroyed, **there is no rollback** — fix forward by issuing a new key and re-encrypting from a clean source.

```bash
# Rollback procedure (Steps 2-6 window)
# 1. Restore old .sops.yaml
git checkout HEAD -- .sops.yaml
# 2. Re-encrypt to old-only recipient set
for f in $(git ls-files | grep '\.sops\.'); do
  sops updatekeys --yes "$f"
done
# 3. Restore the old GitHub secret SOPS_AGE_KEY (operator must keep a copy
#    until verification §5 passes — do NOT discard before then).
# 4. Open a postmortem note in docs/security/audit-history.md describing
#    why the rotation was aborted.
```

---

## 7. What NOT To Do

!!! danger "Anti-patterns that compromise the rotation"
    - **Do not re-use the old public recipient** assuming "the private key is gone now." Ciphertext lives in git history; whoever later obtains the old private key can decrypt every commit at or before the rotation point. For routine rotation this is acceptable (we are not pretending to revoke history); for emergency rotation it is also why §4 re-issues the *secrets themselves*, not just the wrapper.
    - **Do not keep the old private key on the workstation "just in case."** That defeats the rotation. Archive offline or destroy.
    - **Do not rotate without re-running the deploy** (emergency only). The cluster's running pods still have the old secret values mounted; they continue working until restarted. A new pod scheduled later pulls the new values and behaves inconsistently. A planned deploy resolves the split.
    - **Do not commit the new private key.** The pre-commit `detect-private-key` hook will refuse the commit; respect that signal.

---

## 8. Related

- **Operational mechanics of SOPS (editing, encrypting, viewing):** [`../operations/sops-setup.md`](../operations/sops-setup.md)
- **Secrets architecture:** [`../architecture/secrets-management.md`](../architecture/secrets-management.md)
- **Audit history (record the rotation):** [`../security/audit-history.md`](../security/audit-history.md)
- **Supply chain (uses GitHub OIDC, not SOPS — no rotation interaction):** [`../security/supply-chain.md`](../security/supply-chain.md)
- **Disaster recovery (restores across a rotation boundary):** [`disaster-recovery-velero.md`](disaster-recovery-velero.md)
