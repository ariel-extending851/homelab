---
description: Run the appropriate tests and linters for the current context.
---

# Instructions

1.  **Identify Context:**
    * Look at the recently modified files to determine the technology stack.

2.  **Execute Validation Strategy:**

    * **If Terraform (`.tf`):**
        * Run `terraform validate`.
        * Run `terraform fmt -check`.
        * (If available) Run `tflint`.

    * **If Kubernetes (`.yaml`, `.yml`):**
        * Check for valid YAML syntax.
        * Verify required fields (apiVersion, kind, metadata).
        * *Guardrail:* Ensure no hardcoded secrets are present.

    * **If Shell Scripts (`.sh`):**
        * Run `shellcheck` (if installed) or check for common syntax errors.

3.  **Report Results:**
    * If all checks pass, report "✅ All checks passed (Green)".
    * If checks fail, report "❌ Checks failed (Red)" and provide the error logs.
