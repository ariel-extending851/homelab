---
description: Run the appropriate tests and linters for the current context.
---

# Instructions

1. **Identify Context:**
    * Look at the recently modified files (`git status`, `git diff --name-only HEAD`) to determine the layers touched. A change can hit more than one — run all that apply.

2. **Execute Validation Strategy:**

    * **If Python (`*.py`):**
        * `mise exec -- pytest <changed_test_targets> -x --no-cov` — fast feedback, scoped to the changed files (mirrors the `verify-tests.sh` Stop hook).
        * Full suite + 70% coverage gate runs in CI; do NOT run `make test-python` locally for every edit — that's the heavy gate.
        * If you added a new function, also write a test in `bin/tests/test_<script>.py` (per `docs/CONVENTIONS.md` §6.2 — even when the source lives outside `bin/`).

    * **If Terraform (`*.tf`):**
        * `make validate-terraform-all` — runs `terraform fmt -check` + `terraform validate` + `tflint` across `infra/aws`, `infra/aws-backend`, `infra/aws-oidc`.
        * If the touched module has `tests/*.tftest.hcl`, run `terraform test` inside that module dir.

    * **If Ansible role (`ansible/roles/<role>/**`):**
        * `make test-molecule-<role>` — runs that role's Molecule scenario in Docker.
        * If you added new tasks, ensure the scenario verifies them in `verify.yml`.

    * **If Kubernetes manifests (`k8s/**/*.yaml`):**
        * `make validate-k8s-all` — kubeconform schema validation + `kustomize build` for each overlay.
        * `make validate-k8s-policies` — runs OPA / Conftest policies in `k8s/policies/*.rego`.
        * Guardrail: ensure no plaintext secrets; encrypted `secret.yaml` files are picked up by SOPS — never commit decrypted ones.

    * **If Shell (`*.sh`):**
        * `mise exec -- shellcheck <file>` (or rely on pre-commit, which runs it on staged shell).
        * Reminder: `docs/CONVENTIONS.md` §6.2 says **avoid shell scripts** — prefer Python under `bin/`.

    * **If GitHub Actions workflow (`.github/workflows/*.yml`):**
        * `mise exec -- actionlint <file>` for syntax + best-practice checks.
        * `mise exec -- zizmor <file>` for security review of workflow patterns (already in pre-commit).

3. **Report Results:**
    * If all checks pass: `✅ All checks passed (Green)`.
    * If any fail: `❌ Checks failed (Red)` followed by the relevant error excerpt.
    * Never modify test files / fixtures to make a check pass — fix the production code instead (echoed by the Stop hook).
