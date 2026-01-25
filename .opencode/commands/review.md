---
description: Review staged changes before committing using the Tech Lead agent.
---

# Instructions

This command is automatically run by `/commit`. You can also run it manually to check your changes before committing.

## 1. Pre-Flight Check

* Run `git diff --cached --quiet` to verify there are staged changes.
* If nothing is staged, exit with message: "Nothing to review. Stage changes with `git add` first."

## 2. Invoke Tech Lead Agent

Use the Task tool to invoke the tech-lead agent with this prompt:

```
Review the following staged changes for production readiness:

[Insert output of: git diff --cached --stat]
[Insert output of: git diff --cached]

Evaluate against these criteria:

1. **Security (CRITICAL):**
   - No secrets (API keys, passwords, tokens, private keys)
   - No dangerous permissions (chmod 777, privileged containers)
   - No risky capabilities (CAP_CHOWN, CAP_SETUID, CAP_SYS_ADMIN)

2. **Raspberry Pi Constraints:**
   - All containers have resources.limits.memory
   - Memory requests reasonable for Pi nodes (≤512Mi for Pi3, ≤1Gi for Pi4)
   - No heavy I/O on hostPath (SD card constraint)

3. **Naming & Architecture:**
   - kebab-case naming (per docs/conventions.md)
   - ARM64-compatible images (no :latest tags)
   - Proper nodeSelector for Pi vs Oracle nodes

Output format:
- For each issue: Severity (🔴 High | 🟡 Medium | 🟢 Low), file:line, description, fix
- Final recommendation: BLOCK | APPROVE WITH CHANGES | APPROVE
- Save results to .opencode/last-review.md
```

**Agent Configuration:**
* Use: `Task tool` with `subagent_type: "tech-lead"`
* Save response to: `.opencode/last-review.md`

## 3. Process Results

Based on the agent's recommendation:

* **BLOCK:** Exit immediately. Show critical issues and message: "⛔ Fix these issues before committing."
* **HIGH issues found:** Ask user: "Fix issues first? (y/n)". If 'y', exit. If 'n', show warning and continue.
* **APPROVE or APPROVE WITH CHANGES:** Continue to commit phase (if called from `/commit`).

## 4. Integration with /commit

When `/commit` is run, it automatically:
1. Runs this `/review` command first
2. Blocks commit if review returns BLOCK
3. Proceeds to commit message generation if approved

---

**Example Output:**

```
📊 Reviewing staged changes...

🔴 High | k8s/apps/test/deployment.yaml:42
Issue: Container missing memory limits
Fix: Add resources.limits.memory: "512Mi"

Recommendation: BLOCK
⛔ Fix these issues before committing.
```
