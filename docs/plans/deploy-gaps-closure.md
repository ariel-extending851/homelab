# Deploy Gaps Closure

> **Status:** Active
> **Created:** 2026-05-02
> **Owner:** @ariel-extending851
> **Horizon:** ~3 weeks

## Context

A prior analysis of the deploy flow (`bin/deploy_aws_homelab.py` + `Makefile` + `.github/workflows/ci-deployment.yml`) identified 5 concrete gaps where the deploy can silently degrade, asymmetrically behave between local and CI, or destroy debug evidence on failure. This plan closes those gaps and uses the same work to promote `bin/homelab.py` from a diagnostic wrapper to the canonical CLI for human-driven operations.

Language decision: stay in Python. The repo already has ~6k LOC of Python automation, mise toolchain, pytest, and 21 entry points using argparse. Go would mean rewriting working code for zero operational gain — there is no Go anywhere in the repo and no distribution requirement that demands a static binary.

---

## The 5 Gaps (from analysis)

| # | Gap | Location |
|---|---|---|
| 1 | `make deploy` local does not auto-invoke `preflight.py` — gates bypassable | `Makefile:74-80` |
| 2 | SOPS validation only canaries `adguard/secret.yaml`; other broken secrets fail 15min into deploy | `bin/deploy_aws_homelab.py:188-199` |
| 3 | Ansible failure mid-deploy has no resume — partial state forces full rebuild | `bin/deploy_aws_homelab.py:589-591` |
| 4 | CI rollback destroys infra immediately on phase 1-3 failure — no halt-and-investigate | `ci-deployment.yml:925-1001` |
| 5 | `velero_pre_deploy_backup.py` silently no-ops if cluster unreachable — no warning | `bin/velero_pre_deploy_backup.py:12-16` |

Bonus secondary gaps (folded into Phase 4):

- Observability gate runs in parallel with smoke tests — possible race window (`ci-deployment.yml:711-815`)
- Plan binary in `terraform-plan-prod` may be stale by the time `terraform-apply` runs (`ci-deployment.yml:373-377`)
- No isolated unit test for `deploy_aws_homelab.py` orchestration logic — only validated via live staging canary
- `pyproject.toml` measures branch coverage but does not enforce a `fail_under` threshold

---

## Phase 1 (Days 1-5): Foundational Safety

### Objectives

1. Make preflight non-bypassable on `make deploy`
2. Make SOPS validation comprehensive
3. Make pre-deploy backup status loud, not silent

### Deliverables

1. `bin/preflight.py` invoked unconditionally by `Makefile:deploy` target
2. SOPS validation iterates over **every** `k8s/**/secret.yaml` and reports per-file decrypt status
3. `bin/velero_pre_deploy_backup.py` emits a clear warning + sets exit code 2 (not 0) when skipping; CI surfaces this as a yellow gate

### Implementation Tasks

1. **Preflight integration** (`Makefile`, ~10 lines):
   - Add `preflight` as a prerequisite to `deploy` target
   - Add `--skip-preflight` opt-out with stdin confirmation prompt (refuse `--yes` flag)
2. **SOPS deep validation** (`bin/deploy_aws_homelab.py:188-199`):
   - Replace single-canary check with `Path("k8s").rglob("secret.yaml")` loop
   - Report aggregated success/failure; fail fast if **any** file fails
   - Add unit test in `bin/tests/test_deploy_aws_homelab.py` mocking `subprocess.run` for `sops -d`
3. **Velero backup loudness** (`bin/velero_pre_deploy_backup.py:12-16`):
   - Replace silent `sys.exit(0)` with stderr warning + `sys.exit(2)` when cluster unreachable
   - Update CI step to treat exit 2 as `continue-on-error: true` but surface annotation
   - Add unit test for the unreachable-cluster path

### Exit Criteria

1. `make deploy` cannot succeed without preflight passing (verified by integration test)
2. Corrupting any `k8s/**/secret.yaml` makes `make deploy` fail in <30s instead of 15min
3. CI run on a fresh AWS account shows velero-backup yellow annotation, not green

---

## Phase 2 (Days 6-12): CLI Promotion

### Objectives

1. Promote `bin/homelab.py` to the canonical human-facing CLI
2. Replace ad-hoc `python3 bin/X.py` patterns with `homelab <cmd>`
3. Cover the gap in test coverage (`homelab.py` currently has no tests)

### Deliverables

1. `homelab` registered as a `console_scripts` entry point in `pyproject.toml`
2. New subcommands wired to existing modules:

   | Subcommand | Backed by |
   |---|---|
   | `homelab deploy` | `bin/deploy_aws_homelab.py` |
   | `homelab preflight` | `bin/preflight.py` |
   | `homelab smoke` | `bin/smoke_test.py` |
   | `homelab rollback` | `bin/verify_aws_rollback.py` |
   | `homelab backup pre` | `bin/velero_pre_deploy_backup.py` |
   | `homelab backup verify` | calls `make test-velero-restore` |
   | `homelab drift [--fix]` | `bin/drift.py` |
   | `homelab argocd ...` | already present |
   | `homelab k3s ...` | already present |
   | `homelab tf ...` | already present |
3. Unit tests for `homelab.py` subcommand dispatch + arg parsing in `bin/tests/test_homelab.py`

### Implementation Tasks

1. Add `[project.scripts]` section to `pyproject.toml`:
   ```toml
   [project.scripts]
   homelab = "bin.homelab:main"
   ```
2. Add new subcommand groups in `bin/homelab.py` following the existing argparse pattern (no library swap — argparse is already idiomatic here)
3. Each new subcommand imports the existing module's `main()` (or relevant `run_*()`) — no logic duplication
4. Update Makefile help text to point to `homelab <cmd>` as the recommended invocation; keep `make` targets as thin shims (CI continues to call `make`, humans use CLI)
5. Add `bin/tests/test_homelab.py` covering: subcommand dispatch table, argv passthrough, exit code propagation, `--help` output for each subcommand

### Exit Criteria

1. `pip install -e .` makes `homelab` available globally
2. `homelab --help` lists all subcommands; each subcommand has working `--help`
3. `bin/tests/test_homelab.py` covers ≥80% of `homelab.py` lines
4. `docs/CONVENTIONS.md` updated: humans → CLI, CI → make targets

### Non-goals for this phase

- Migrating away from argparse (Typer/Click is a future cosmetic upgrade, not a gate)
- Removing Makefile targets (they remain the CI entry point)

---

## Phase 3 (Days 13-18): Resilience and Recoverability

### Objectives

1. Make Ansible-stage failures resumable instead of forcing full rebuild
2. Replace immediate destroy-on-failure with a halt-and-investigate state in CI
3. Close the asymmetry between local and CI failure paths

### Deliverables

1. `homelab deploy --resume-from=<stage>` flag that skips already-completed stages by reading a deploy state file
2. CI failure mode toggle: `HALT_ON_DEPLOY_FAILURE` env var (default: halt). When set, CI tags infra `do-not-destroy=true`, opens a GitHub issue with the failure context, and parks the workflow until manual `workflow_dispatch` of `rollback.yml`
3. Standalone `rollback.yml` workflow that runs `terraform destroy` + `homelab rollback` on demand

### Implementation Tasks

1. **State file for resume** (`bin/deploy_aws_homelab.py`):
   - On each stage completion, write `.deploy-state.json` to project root with `{stage: completed_at}` map
   - On `--resume-from=ansible`, skip terraform/preflight/SOPS phases if state shows them complete and not stale (>2h triggers re-validation)
   - Add `homelab deploy reset-state` to clear the file
2. **Halt-on-failure** (`ci-deployment.yml:925-1001`):
   - Replace direct destroy job with conditional logic: if `HALT_ON_DEPLOY_FAILURE` true (default), tag instances and open issue; else fall through to existing destroy
   - Use `gh issue create --label deploy-failure` with run URL, failed step, and link to logs
3. **rollback.yml workflow**:
   - Manual `workflow_dispatch` trigger only
   - Inputs: `confirmation` (must literally be `ROLLBACK`), `reason` (free text for audit log)
   - Runs `terraform destroy` + `verify_aws_rollback.py`
4. Tests:
   - Unit test for resume logic (mock state file scenarios)
   - Tests for both halt and direct-destroy paths in `ci-deployment.yml`

### Exit Criteria

1. Killing Ansible mid-run, then `homelab deploy --resume-from=ansible` completes without re-running terraform
2. Forcing CI deploy failure with `HALT_ON_DEPLOY_FAILURE=true` leaves infra alive and creates a GitHub issue
3. Manual `rollback.yml` dispatch successfully tears down halted infra
4. Local `homelab deploy` failure leaves a parseable state file for re-runs

---

## Phase 4 (Days 19-21): Test and Gate Hardening

### Objectives

1. Cover `deploy_aws_homelab.py` orchestration with isolated unit tests
2. Enforce coverage threshold in `pyproject.toml`
3. Sequence post-deploy gates correctly (no race between observability and smoke)
4. Add `tflint` to terraform validation

### Deliverables

1. `bin/tests/test_deploy_aws_homelab_orchestration.py` testing stage ordering, error propagation, rollback triggers — fully mocked, no AWS
2. `pyproject.toml` enforces `--cov-fail-under=80` (current: 90% coverage; threshold of 80 prevents regression with margin)
3. `ci-deployment.yml` runs `post_deploy_observability_gate.py` **before** smoke + e2e (sequential, not parallel)
4. `tflint` added to `.mise.toml` and run via `make validate-terraform-all` (tflint config already mentioned in memory but never wired)

### Implementation Tasks

1. Orchestration tests: parameterize over stage failure points (terraform fails / ansible fails / argocd fails) and assert correct error messages, exit codes, and side effects
2. Add `fail_under = 80` to `[tool.coverage.report]` in `pyproject.toml`; bump CI runner to use `--cov-fail-under=80`
3. Restructure `ci-deployment.yml` job graph: `argocd-wait` → `observability-gate` → `smoke-test` → `e2e-tests` → `velero-restore-test`
4. Wire `tflint`:
   - Add `tflint = "0.55.1"` to `.mise.toml`
   - Create `.tflint.hcl` at repo root with conservative rules
   - Add `tflint --recursive infra/aws/` to `Makefile:validate-terraform-all`
5. Address terraform plan-staleness: add `terraform plan -detailed-exitcode` re-check immediately before `terraform apply` in `ci-deployment.yml:373-377` and fail if plan changed

### Exit Criteria

1. `make test-python` passes with `--cov-fail-under=80` enforced
2. `bin/tests/test_deploy_aws_homelab_orchestration.py` covers all 4 main stages with mocked subprocess
3. CI deploy job graph is sequential through gates; demonstrated by introducing a fake CrashLoopBackOff and confirming smoke test does NOT run
4. `tflint` flags at least one finding on first run (or explicitly green if clean)

---

## Out of Scope for This Plan

1. Migrating argparse → Typer/Click (cosmetic; revisit after Phase 4 ships)
2. Replacing Makefile entirely (CI keeps using it; humans switch to CLI)
3. Building a new policy framework (existing OPA/conftest is sufficient)
4. Distribution as a static binary (Python install is fine for this team)
5. Migrating `.bats` tests to Python (already analyzed — keep as-is)

## Cross-cutting Verification

After all phases ship, the following should hold end-to-end:

```bash
# 1. CLI is the canonical human entry point
homelab --help                       # lists 9+ subcommands

# 2. Preflight cannot be silently bypassed
make deploy                          # auto-runs preflight; refuses --yes for skip

# 3. Resume works
homelab deploy                       # interrupt during ansible
homelab deploy --resume-from=ansible # skips terraform, picks up at ansible

# 4. Halt-on-failure works in CI
gh workflow run ci-deployment.yml -f force_failure=ansible
# → infra alive, issue opened, no auto-destroy

# 5. Coverage enforced
make test-python                     # fails if any PR drops coverage below 80%

# 6. Sequential gates
# Forced CrashLoopBackOff after argocd-wait → observability-gate fails BEFORE smoke runs
```

## Tracking

Each phase ships as one PR (or 2 if size warrants). Update the status table at the top as phases complete:

| Phase | Status | PR | Completed |
|---|---|---|---|
| 1 — Foundational Safety | ✅ Done (local) | — | 2026-05-02 |
| 2 — CLI Promotion | ✅ Done (local) | — | 2026-05-02 |
| 3 — Resilience | ✅ Done (local) | — | 2026-05-02 |
| 4 — Test & Gate Hardening | ✅ Done (local) | — | 2026-05-02 |
