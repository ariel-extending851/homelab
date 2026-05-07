---
description: Analyze changes and generate a Verified (GPG) Conventional Commit with detailed body.
---

# Instructions

## Pre-Commit Review Gate

**CRITICAL:** Before generating a commit message, you MUST run the `/review` command to ensure code quality and security.

1. **Invoke `/review` Command:**
    * Execute all steps defined in `.claude/commands/review.md`
    * The tech-lead agent will review staged changes for:
      - Security issues (secrets, permissions, capabilities)
      - Raspberry Pi constraints (memory limits, I/O patterns)
      - Naming conventions (kebab-case, hl- prefix)
      - Architecture violations (ARM64, nodeSelector, etc.)
    * Review results are saved to `.claude/cache/last-review.md`

2. **Process Review Results:**
    * If review recommendation is **BLOCK**: Exit immediately (do NOT proceed to commit)
    * If **HIGH severity** issues found: Ask user if they want to fix issues first
    * If user chooses to fix: Exit and let user run `/commit` again after fixes
    * If **APPROVE** or user overrides warnings: Proceed to Step 3

3. **Proceed to Commit Phase:**
    * Only continue to commit message generation if review passed or user explicitly approved

## Commit Message Generation

4. **Analyze Context:**
    * Run `git status` to see what is staged vs. unstaged.
    * Run `git diff --cached` to see the actual changes to be committed.
    * If nothing is staged, run `git diff` and ask user if they want to stage changes.

5. **Generate Message (Strict Format):**
    * **Header:** `<type>(<scope>): <concise description>` (Max 50 chars).
    * **Body:** A detailed bulleted list explaining *what* and *why*.
    * **Constraint:** The body MUST be a compact list (no empty lines between bullets).

    *Example Format:*

    ```text
    docs(searxng): add comprehensive README for deployment

    - Document deployment components and architecture
    - Add step-by-step deployment instructions
    - Include troubleshooting guide
    - Document resource limits and constraints
    ```

6. **Review & Execute (Technique):**
    * Present the full message to the user for approval.
    * **CRITICAL:** To avoid extra spacing, use **EXACTLY TWO** `-m` flags:
        1. The first `-m` is for the **Header**.
        2. The second `-m` contains the **Entire Body** (pass the list as a single multi-line string).
    * **Command Template:**

        ```bash
        git commit -S -m "<Header>" -m "- <Detail 1>
        - <Detail 2>
        - <Detail 3>"
        ```

    * *Note for Agent:* When generating the command, ensure the second `-m` opens a quote, lists the items on new lines, and closes the quote at the end.

7. **Verification:**
    * Run `git log -1` to confirm the formatting is correct (Header, empty line, compact list).
