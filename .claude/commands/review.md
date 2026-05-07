---
description: Pre-commit review of staged changes via the tech-lead subagent.
---

# Instructions

## 1. Capture staged diff

```bash
git diff --cached --stat
git diff --cached
```

If there are no staged changes, report `ℹ️ No staged changes to review` and exit.

## 2. Delegate to the tech-lead agent

Invoke the `tech-lead` subagent (Agent tool, `subagent_type: tech-lead`) with the staged diff. The agent must check, in order:

1. **Security** — secrets in plaintext, missing resource limits, `:latest` tags in production manifests, `chmod 777`, capability creep.
2. **RPi constraints** — memory/CPU limits set; nodeSelector when needed; ARM64 compatibility for images deployed to Pi nodes.
3. **Naming conventions** — `hl-` prefix on cloud/k8s resources outside project namespaces; `kebab-case` filenames and resource names (`docs/CONVENTIONS.md`).
4. **Architectural integrity** — no bypassing of SOPS/ArgoCD CMP; no shell scripts (use Python — `docs/CONVENTIONS.md` §6.2); Molecule tests present for new Ansible roles.

## 3. Required output format

The agent MUST emit, as the **first line** of its response, exactly one of:

- `APPROVE` — no blocking issues
- `WARN` — non-blocking concerns, may proceed
- `BLOCK` — must be fixed before commit

Followed by bulleted findings grouped by category (Security, RPi, Naming, Architecture). One bullet per finding, file path + line number where applicable.

## 4. Persist the verdict

Write the agent's full response to `.claude/cache/last-review.md` (gitignored — see `.gitignore`). Create the directory if it does not exist:

```bash
mkdir -p .claude/cache
```

Print the verdict line to stdout so the calling `/commit` workflow can read it.

---

**Usage:**

```bash
/review               # called directly or transparently from /commit
```

**Exit semantics for the caller:**

- `APPROVE` → caller may proceed to commit
- `WARN` → caller asks user whether to proceed
- `BLOCK` → caller exits without committing
