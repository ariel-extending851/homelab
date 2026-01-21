---
description: Review progress and update .opencode/plan.md automatically.
---

# Instructions

1. **Analyze Progress:**
    * Read `.opencode/plan.md` to see the current active tasks.
    * Run `git log --oneline -n 10` to see recent work.
    * Compare the commits against the open tasks.

2. **Update the Plan:**
    * Mark completed tasks with `[x]`.
    * If new sub-tasks were discovered (e.g., during a `/learn` session), add them to the list.
    * **Constraint:** Do NOT remove completed tasks; keep them for history. Only mark them as done.

3. **Report:**
    * Show the user the updated section of the plan.
    * Suggest the immediate next command to run based on the next open task.
