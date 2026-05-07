# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Orientation

This is a hybrid k3s homelab spanning AWS EC2 spot instances and Raspberry Pi nodes, reachable only over Tailscale, deployed via Terraform + Ansible + ArgoCD. Before substantive work, read:

- [`README.md`](README.md) — architecture diagram + tooling table
- [`docs/README.md`](docs/README.md) — documentation hub (80+ docs across architecture, operations, runbooks, services, security)
- [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) — naming, versioning, and the **code & test placement table** (section 6.2)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — local-test-before-push commands and Ansible-role rules

`make help` lists every target with its inline description; treat the Makefile as the catalog of operations.

## Common Commands

```bash
make deploy                   # full stack (auto-runs preflight); same as: python3 bin/deploy_aws_homelab.py
make destroy                  # tear down AWS infra
make ansible-deploy           # re-run config without Terraform
make smoke-test               # post-deploy HTTP checks across all apps
make validate                 # all syntax + connectivity checks
make validate-terraform-all   # terraform fmt + validate + tflint across all 3 modules
make validate-k8s-all         # kubeconform + kustomize build across k8s/
make test-python              # pytest with inline coverage (70% gate)
make test-molecule-<role>     # single Ansible role: e.g. test-molecule-k3s
make new-role ROLE=<name>     # scaffold from templates/ via Copier (required: every role MUST have molecule/default/)
make new-app  APP=<name>      # scaffold a k8s app from templates/
```

Run a single Python test:

```bash
mise exec -- pytest bin/tests/test_<script>.py::test_<case> -xvs
```

Run a single Molecule scenario directly:

```bash
cd ansible/roles/<role> && mise exec -- molecule test
```

## CLI vs Make (Two Surfaces, Same Code)

`homelab <cmd>` is a `console_scripts` entry point (registered in `pyproject.toml` → `bin.homelab:main`) that routes to the same `bin/*.py` scripts that `make` invokes. Adding a new subcommand: see `docs/CONVENTIONS.md` §7.3. There is no logic divergence between the two surfaces — `homelab` is for humans, `make` is what `.github/workflows/*.yml` calls.

## Architecture (the cross-file picture)

### Deploy chain (`bin/deploy_aws_homelab.py`)

Resumable per-phase via a state file:

1. **Prerequisites** — SOPS key + AWS account + tool checks
2. **Terraform** — `infra/aws/` apply; SOPS-encrypted `terraform.tfvars.sops.yaml`; remote state in S3 + DynamoDB lock
3. **Instance wait** — SSM polling for EC2 ready (Zero Trust: no public SSH)
4. **Tailscale wait** — both nodes get `100.x` CGNAT IP
5. **Ansible** — `ansible/playbooks/site.yml` with phased tags (`phase0` cleanup → `phase1` infra → `phase2` GitOps → `phase3` verify); dynamic inventory from Terraform output
6. **Verify** — fetch kubeconfig via SSM, rewrite server URL to Tailscale IP, save to `/tmp/k3s-homelab-kubeconfig.yaml`

### GitOps layout (`k8s/`)

- `k8s/gitops/apps-root.yaml` is the **App-of-Apps root** (single ArgoCD `Application` pointing to `k8s/apps`).
- `k8s/apps/<app>/` — per-app Kustomize manifests; folder name matches namespace.
- `k8s/system/` — platform components (tailscale-operator, kyverno, cilium, longhorn, etc.).
- `k8s/policies/` — OPA/Conftest `*.rego` policies.
- **SOPS at sync time:** ArgoCD uses a CMP plugin (`k8s/gitops/sops/argocd-repo-server-patch.yaml`) to decrypt `secret.yaml` files at sync time — there is no External Secrets Operator. Encrypted secrets live in Git as `**/secret.yaml`.

### Tailscale ingress

Apps expose themselves via `ingressClassName: tailscale` plus `tailscale.com/proxy-class:` annotation. The `ProxyClass` CRDs in `k8s/system/tailscale-operator/` set `nodeSelector` to spread proxies and avoid memory pressure on the 2GB k3s server.

### Terraform layout (`infra/`)

- `infra/aws/` — main stack (network / compute / scheduler / audit modules); workspaces: default = prod, optional `staging` (`make terraform-staging-*` + `staging.tfvars`).
- `infra/aws-backend/` — one-time S3 state bucket + DynamoDB lock table bootstrap.
- `infra/aws-oidc/` — one-time GitHub Actions OIDC provider + IAM role for CI.

### Pre-deploy gates (`bin/`)

- `preflight.py` — chain checks (SOPS canary, Tailscale reachability, SSM, kubeconfig sanity, AWS creds, git hygiene). Runs automatically before `make deploy` unless `SKIP_PREFLIGHT=true` (requires typed confirmation).
- `infracost_diff_gate.py` — cost-delta gate.
- `k3d_convergence.py` — local k3d cluster + ArgoCD App-of-Apps convergence test.

## Conventions That Bite

From `docs/CONVENTIONS.md`:

- **All resources use `hl-` prefix + `kebab-case`** (cloud, k8s, repos, doc filenames). The `hl-` prefix may be omitted for app-specific resources inside a project-scoped namespace.
- **Python tests live in `bin/tests/`** even when the source script lives elsewhere (`ansible/`, `infra/aws/scripts/`). One pytest config in `pyproject.toml`; shared `conftest.py` is in `bin/tests/`. **Exception:** Lambda packages keep tests co-located in `infra/aws/modules/<module>/lambda_src/tests/` because the package is zipped as a unit.
- **Avoid shell scripts.** Prefer Python; existing shell logic was migrated in commit `9eecfcc`.
- **Every Ansible role MUST have `molecule/default/`.** CI's `enforce-molecule-tests` job rejects PRs adding a role without it.
- **Secrets are SOPS+age encrypted.** Never commit plaintext; pre-commit and CI both reject. SOPS key path: `~/.config/sops/age/keys.txt` (also referenced by `.mise.toml` env). Editing: see `docs/operations/sops-setup.md`.

## Tooling

`.mise.toml` is the **single source of truth for tool versions** — local dev and CI both run `mise install` to get an identical environment. Makefile `setup-ci-deps-*` targets call `mise exec --` to verify and supplement (e.g. injecting `boto3` into the ansible-core venv). When adding a new tool, pin it in `.mise.toml` first.

When running tools, prefer `mise exec -- <cmd>` over a bare command so local and CI behave the same.

## CI

`.github/workflows/ci-validation.yml` runs ~13 parallel jobs (terraform, kubeconform, conftest, molecule, molecule-arm64 via QEMU, pytest, shellcheck, yamllint, TruffleHog, Checkov, etc.); `pipeline-gate` aggregates required jobs. `ci-deployment.yml` is the manual CD pipeline that calls `make` targets — keeping the Makefile as source of truth means local runs equal CI runs.

## When making changes

- Touching Terraform → run `make validate-terraform-all` + relevant `*.tftest.hcl` under `infra/<dir>/tests/`.
- Touching an Ansible role → run that role's `make test-molecule-<role>`; if creating a new role, use `make new-role ROLE=<name>` (Copier scaffolds the required structure).
- Touching k8s manifests → `make validate-k8s-all` and `make validate-k8s-policies`.
- Touching Python under `bin/` or `ansible/scripts/` → `make test-python` (70% coverage gate enforced in CI).
- Adding a new ingress hostname → also update `docs/reference/tailnet-services.md` (CONTRIBUTING.md mandates this).
- Significant security or architecture change → add an entry to `docs/security/audit-history.md`.

## How we work here

Principles that shape every change in this repo. They map Extreme Programming and Clean-Code-for-agents to infra constraints.

1. **Cada commit é production-ready.** If `make validate-*` fails locally, it doesn't get pushed. CI's 13-job gate is the safety net, not the first signal.
2. **Idempotência > correção.** A new Ansible task or Terraform resource isn't done until running it twice produces the same state. `make test-ansible-idempotency` and `*.tftest.hcl` are gates, not formalities.
3. **Refactoring contínuo.** Touch a dirty file, clean it now — don't queue a "cleanup PR". Deferred refactors become 5,000-line files (Akita's FrankMD postmortem proved it empirically).
4. **Humano decide o quê. Agente propõe o como.** For destructive or expensive operations (`terraform destroy`, `kubectl delete ns`, manual SSM patches, anything touching running prod), Claude STOPS and asks even if the local hooks already warn. Hooks catch syntax; humans catch intent.
5. **One-shot é mito.** Expect 2-3x more commits AFTER first deploy than before it (Akita: 274 + 125 across 4 projects). Plan for sustained iteration, not a heroic launch.
6. **Phased delivery.** A "works locally" commit and a "production-ready" commit are distinct units. Don't merge them: Phase 1 = it runs end-to-end; Phase 2 = idempotency + retry/timeout + observability + docs. Skipping Phase 2 produces tech debt that compounds.
7. **Right tool for right job.** Use the agent for boilerplate, scaffolding, docstrings, refactors, test generation. Apply human freios on novel domain logic (k3s networking, Tailscale + ArgoCD CMP integration, SOPS rotation, IAM policy design). The agent's average is the training-set average; for non-average problems, you steer.
8. **Hurdles documentados no mesmo PR.** When you discover a non-obvious failure mode, add an entry to `docs/runbooks/` or auto-memory **in the same PR that fixes it**. The next session reads `CLAUDE.md` + runbooks before acting; what's not written gets re-discovered the hard way.

## Working with the agent

Operational hygiene specific to running Claude Code (or any LLM agent) on this repo.

- **Spec before prompt.** For non-trivial work, draft an `IDEA.md` / plan file / GitHub issue first stating goal, constraints, and out-of-scope. Without a contract, the agent ships "training-set average" — fine for boilerplate, wrong for k3s/Tailscale/SOPS work. Plan mode in Claude Code already enforces this; honor it.
- **Token economy.** Every plugin / skill / MCP server adds 80–250 tokens to every session. Audit `.claude/settings.json` and installed skills periodically — uninstall anything not used in the last month. Prompts in `.claude/commands/` and the agent persona in `.claude/agents/` are version-controlled like code; prefer compact directives over prose.
- **No auto-commit.** The agent NEVER commits without an explicit human ack ("commit this" / "open PR"). Re-state this when configuring new agent CLIs (Aider, Cline, Cursor) that may default to auto-commit.
- **Multi-model agnostic.** Models change quarterly (Opus 4.7 → 4.8 → …). Don't hardcode model names in scripts; reference via env (`CLAUDE_MODEL`) or `.mise.toml` so a model bump is one config change, not a sweep. Same applies to image tags and Helm chart versions.

## Code style for agents

These rules are written for AI agents reading this repo. Humans editing the same files follow them too — they map Clean Code to infra-as-code constraints.

### Size (truncation-aware)

- **Terraform module file**: under 500 lines per `.tf`. Split by resource type (network / compute / scheduler — already the pattern in `infra/aws/modules/`).
- **Ansible role**: if `tasks/main.yml` exceeds ~150 lines, split into `tasks/<concern>.yml` and include with `import_tasks:`.
- **Python script (`bin/*.py`)**: under 300 lines; one concern per file with a `main(argv=None)` entry point.
- **Function / task**: 4–20 lines. Longer = doing too much.

### Names (grepable)

- All resources: `hl-` prefix + `kebab-case` (already enforced — see `docs/CONVENTIONS.md`).
- Terraform variable / output names include the resource scope: `k3s_server_instance_id`, not `instance_id`.
- Ansible task names are imperative + specific: `Install k3s server binary`, not `Setup`.
- Test before naming: `rg <name>` should return under 5 matches in this repo. If it returns more, the name is too generic.

### Types and contracts

- **Terraform**: every variable has `type = …` and `description = …`. Outputs have `description`. Use `precondition`/`postcondition` for invariants the operator cares about (e.g. spot price ceiling, AZ presence).
- **Ansible**: `assert:` early in a play if a required variable / fact is missing. Failure messages include the offending value.
- **Python**: type hints on every function signature. Errors include context — `raise ValueError(f"expected non-empty bucket, got {value!r}")`, not `raise ValueError("invalid input")`.

### Comments (proveniência, not narration)

- **Keep AI-authored comments.** If Claude (or another agent) wrote a comment in a prior turn, do NOT strip it on refactor — it preserves intent the next session will need. This is counterintuitive vs. the 2008 Clean Code rule and is intentional.
- Write the WHY, not the WHAT. `# install nginx` above `apt: name=nginx` is noise. `# k3s server install does not detect stale --node-ip; see runbook` is signal.
- Reference: link to runbook, issue number, commit SHA, or upstream bug when the line exists for a non-obvious reason.

### DRY and DI

- No hardcoded ARNs, AMIs, or region strings. Pass via `variable "..."` in Terraform, via `group_vars/host_vars` in Ansible, via env in Python (`os.environ`, validated at startup).
- Helm/Kustomize: pin versions in `kustomization.yaml`; never `latest`.
- Duplicated logic across modules → extract. Agents can break two of three copies and pass tests on the third; DRY removes that failure mode.

### Defensive code (only where this list says so)

The agent does NOT infer when defensive patterns are needed — instruct explicitly. Today's required spots:

- **Lambda scheduler**: timeout 30s, retries 2, dead-letter to CloudWatch.
- **Ansible `kubectl wait` tasks**: `async: 600 poll: 10` to survive SSM idle limits.
- **Python AWS-API calls in `bin/`**: use `botocore` retry config (already in `bin/deploy_aws_homelab.py`).
- **ArgoCD app sync**: use `retry: { limit: 5, backoff: ... }` in app manifests.
- **Domain-specific exceptions for retryable Python jobs**: don't use bare `except Exception` — name the failure (`SSMTimeoutError`, `KubeWaitTimeout`, `TerraformLockHeld`) so retry policy can be per-class.
- **Idempotency keys for restartable operations**: `bin/deploy_aws_homelab.py` already does this via `.deploy-state.json`. Apply the same pattern to any new long-running script (Velero restore, image upgrade sprint, SOPS rotation) so re-running after partial failure is safe.

If you add a new operational hot path, add it to this list (same PR).

### Formatting (don't debate)

Pre-commit owns it: `terraform fmt`, `black`, `ruff`, `yamllint`, `ansible-lint`, `shellcheck`, `markdownlint`. Run `pre-commit install` once; CI re-runs on every PR. Don't argue tab vs. space, brace style, or column width.

## Search & context strategy

This repo is designed to be navigated by `rg` / `Glob`, not by vector embeddings. Two consequences:

- **Use grep first.** `rg "<unique-name>"` returns the right hit because names are scoped (`k3s_server_user_data`, `hl-tailscale-operator`). Fall back to `Read` only when you have the path.
- **Paths are predictable.** `infra/aws/modules/<x>/` implies `main.tf` + `variables.tf` + `outputs.tf` (+ `tests/*.tftest.hcl`). `ansible/roles/<x>/` implies `tasks/main.yml` + `defaults/main.yml` + `molecule/default/`. `k8s/apps/<x>/` implies `kustomization.yaml` + (encrypted) `secret.yaml`. Don't `find` what you can derive.
- **Runbooks are ground truth for hurdles** (see next section). When operating on something fragile, read the runbook before assuming the obvious approach works.

## Common hurdles

Real failure modes this project has hit. Read the linked runbook before assuming the obvious approach works.

- **EBS-swap between EC2s blocked by fleet** — Day-2 deploy 2026-05-05. Cannot move EBS into a fleet-launched instance; required full re-deploy onto fresh EBS. See [`docs/runbooks/prod-deploy-2026-05-05-postmortem.md`](docs/runbooks/prod-deploy-2026-05-05-postmortem.md).
- **Tailscale logout silences the entire cluster** — Admin-side device removal makes the API unreachable. Recovery requires SSM session + manual `tailscale logout`/`tailscale up` + sed-patch of stale `--node-ip` in `k3s.service`. See [`docs/runbooks/tailscale-logged-out.md`](docs/runbooks/tailscale-logged-out.md).
- **k3s server install doesn't detect stale `--node-ip`** — The agent role does, the server role doesn't (yet). After IP changes, `k3s.service` keeps the old `--node-ip` and the cluster won't form. Tracked as code follow-up in auto-memory `project_prod_deploy_2026_05.md`.
- **Staging deploys must override the SSM bucket** — `.mise.toml` env defaults `ANSIBLE_AWS_SSM_BUCKET_NAME=homelab-ssm-transfer-bucket` (prod). Staging requires `ANSIBLE_AWS_SSM_BUCKET_NAME=homelab-ssm-transfer-bucket-staging make ansible-deploy`. Gotcha #1 in [`docs/runbooks/staging-deploy-2026-05-postmortem.md`](docs/runbooks/staging-deploy-2026-05-postmortem.md).
- **`ansible kubectl wait` times out under SSM** — SSM session has shorter idle limits than `kubectl wait`. Long-running waits need `async:`/`poll:`. Code follow-up in auto-memory `project_prod_deploy_2026_05.md`.
- **Control plane unresponsive after deploy** — Often a node-ip mismatch or kube-apiserver flapping; do NOT destroy and re-create blindly. See [`docs/runbooks/control-plane-recovery.md`](docs/runbooks/control-plane-recovery.md).
