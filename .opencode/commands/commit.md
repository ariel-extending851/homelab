---
description: Analyze changes and generate a Verified (GPG) Conventional Commit.
---

# Instructions

1.  **Analyze Context:**
    * Run `git status` to see what is staged vs. unstaged.
    * Run `git diff --cached` to see the actual changes to be committed.
    * If nothing is staged, run `git diff` and ask user if they want to stage changes.

2.  **Generate Message:**
    * Create a commit message following **Conventional Commits**: `<type>(<scope>): <description>`.
    * **Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `infra`.
    * **Scope:** The module affecting the change (e.g., `oci`, `k8s`, `readme`, `devx`).
    * **Body:** For complex changes, add a bulleted list explaining *why* and *what*.
    * *Constraint:* Ensure the message is concise and professional.

3.  **Review & Execute (Security First):**
    * Present the message to the user inside a code block.
    * Ask: "Ready to commit?"
    * **CRITICAL:** When executing, YOU MUST use the `-S` flag to sign the commit.
    * Command template: `git commit -S -m "<type>(<scope>): <message>"`
    * *Note:* If the commit has a body, use multiple `-m` flags: `git commit -S -m "title" -m "body line 1" -m "body line 2"`

4.  **Verification:**
    * Run `git log -1 --show-signature`.
    * Verify that the output contains "Good 'git' signature".
