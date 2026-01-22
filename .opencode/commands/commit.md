---
description: Analyze changes and generate a Verified (GPG) Conventional Commit with detailed body.
---

# Instructions

1. **Analyze Context:**
    * Run `git status` to see what is staged vs. unstaged.
    * Run `git diff --cached` to see the actual changes to be committed.
    * If nothing is staged, run `git diff` and ask user if they want to stage changes.

2. **Generate Message (Strict Format):**
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

3. **Review & Execute (Technique):**
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

4. **Verification:**
    * Run `git log -1` to confirm the formatting is correct (Header, empty line, compact list).
