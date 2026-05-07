---
description: Update project memory with a new lesson or fact.
---

# Instructions

1. **Analyze the Lesson:**
    * Identify the new fact, constraint, or fix pattern provided by the user or discovered during debugging.
    * Example: "The restart command needs `sudo` on the RPi nodes."

2. **Update Memory:**
    * Use Claude Code auto-memory at `/home/vscode/.claude/projects/-workspaces-homelab/memory/`.
    * Choose the appropriate type (`user`, `feedback`, `project`, `reference`) per the auto-memory rules in CLAUDE.md.
    * Write the memory to its own file (e.g. `feedback_<topic>.md`) and add a one-line pointer to `MEMORY.md`.
    * Keep it concise; lead with the rule/fact, then add **Why:** and **How to apply:** lines for `feedback`/`project` types.

3. **Confirm:**
    * Report back: "🧠 Memory updated: [Summary of lesson]"
