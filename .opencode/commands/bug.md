---
description: Handle a bug report using strict TDD (Reproduction First).
---

# Instructions

1. **Reproduction (The "Red" Phase):**
    * Do NOT fix the code yet.
    * Create a reproduction script (e.g., `tests/repro_issue_X.sh` or a unit test) that demonstrates the failure.
    * Run the script and confirm it FAILS.

2. **Fix (The "Green" Phase):**
    * Modify the code to resolve the issue.
    * Run the reproduction script again.
    * It must PASS now.

3. **Cleanup (Refactor):**
    * Remove the temporary reproduction script (or convert it to a permanent regression test).
    * Commit with `fix(<scope>): <description>`.
