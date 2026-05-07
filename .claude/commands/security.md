---
description: Security audit of staged changes via the security-reviewer subagent.
---

# Instructions

Targeted security review for changes touching IAM, RBAC, SOPS, NetworkPolicy, image pins, or supply-chain config. For general code review use [`/review`](review.md) instead.

## 1. Detect security-relevant changes

```bash
git diff --cached --name-only
```

Match the staged paths against any of:

- `infra/**/*iam*.tf`, `infra/**/*role*.tf`, `infra/aws-oidc/**`
- `k8s/**/secret.yaml`, `**/*.sops.*`
- `k8s/system/network-policies/**`, `**/networkpolicy*.yaml`
- `k8s/**/clusterrole*.yaml`, `k8s/**/rolebinding*.yaml`
- `.trivyignore*`, `.checkov.baseline`, `.trivy-image-allowlist.txt`
- `**/Dockerfile`
- `kustomization.yaml` lines that pin `images:` (run `git diff --cached -- '**/kustomization.yaml' | rg '^[+-].*images:'` to confirm)

If nothing matches:

> ℹ️ No security-relevant changes detected. Run `/review` for a general pre-commit review.

…and exit.

## 2. Delegate to security-reviewer

Invoke the `security-reviewer` subagent (Agent tool, `subagent_type: security-reviewer`) with:

- `git diff --cached` output
- The list of matched paths from step 1
- A note instructing the agent to read `docs/security/audit-history.md` and `.trivyignore.yaml` before judging

## 3. Required output format

The first line of the agent's response must be exactly one of:

- `APPROVE` — no blocking issues
- `WARN` — non-blocking concerns, may proceed
- `BLOCK` — must be fixed before commit

Followed by findings grouped by category: `IAM`, `RBAC`, `SOPS`, `NetworkPolicy`, `Image`, `Allowlist`, `SupplyChain`. One bullet per finding with file path + line number where applicable.

## 4. Persist the verdict

```bash
mkdir -p .claude/cache
```

Write the agent's full response to `.claude/cache/last-security-review.md` (gitignored). Print only the verdict line to stdout.

---

**Usage:**

```bash
/security              # called manually before /commit on PRs touching the patterns above
```

**Exit semantics for the caller:**

- `APPROVE` → caller may proceed
- `WARN` → caller asks user whether to proceed
- `BLOCK` → caller exits without committing
