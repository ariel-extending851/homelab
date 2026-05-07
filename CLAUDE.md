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
