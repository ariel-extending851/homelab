# Makefile Targets

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Reference for every target in the root [`Makefile`](../../Makefile). For detailed workflow guides see [`../operations/`](../operations/).

Run `make help` to see this list with the live inline `## comments`.

---

## Bootstrap & Deployment

| Target | Purpose |
|---|---|
| `setup` | Install all tools and dependencies (run this first) |
| `ansible-galaxy-install` | Install Ansible collections from `requirements.yml` |
| `deploy` | **Full deploy** — Terraform → Ansible → ArgoCD → apps |
| `deploy-safe` | Run all tests then `deploy` if they pass |
| `deploy-quick` | Deploy without verification (faster, riskier) |
| `destroy` | Tear down all AWS infrastructure (interactive confirm) |

## Terraform

| Target | Purpose |
|---|---|
| `terraform-init` | One-time per machine |
| `terraform-plan` | Review changes |
| `terraform-apply` | Provision (or update) |
| `terraform-output` | Dump all outputs |
| `terraform-state` | List Terraform state resources |

Detail: [`../operations/terraform.md`](../operations/terraform.md).

## OIDC (one-time)

| Target | Purpose |
|---|---|
| `oidc-init` | Bootstrap GitHub Actions OIDC role in AWS |
| `oidc-plan` | Preview OIDC bootstrap changes |
| `oidc-apply` | Create OIDC provider + IAM role (run once) |
| `oidc-output` | Show OIDC role ARN (paste into GitHub) |

## Ansible

| Target | Purpose |
|---|---|
| `ansible-ping` | Test Ansible connectivity to all hosts |
| `ansible-inventory` | Show dynamic inventory |
| `ansible-deploy` | Run `site.yml` playbook (auto-refreshes kubeconfig) |
| `ansible-check` | Dry-run of `site.yml` |
| `ansible-health` | Health check across the cluster |
| `ansible-router` | Configure GL.iNet Opal router (gatekeeper role) |
| `clean-tailscale` | Prune stale Tailscale nodes |
| `ansible-emergency` | Run emergency recovery playbook |

Detail: [`../operations/ansible.md`](../operations/ansible.md).

## ArgoCD

| Target | Purpose |
|---|---|
| `argocd-password` | Get ArgoCD admin password |
| `argocd-port-forward` | Port-forward to <https://localhost:8080> |
| `validate-argocd-synced` | Wait until apps-root is Synced + Healthy (used by CI/CD) |

## Status & Logs

| Target | Purpose |
|---|---|
| `status` | Overall infrastructure status |
| `logs-terraform` | Show Terraform logs |
| `logs-ansible` | Show Ansible logs |
| `k8s-nodes` / `k8s-pods` / `k8s-apps` / `k8s-ingress` | kubectl shortcuts |
| `k8s-kubeconfig` | Refresh local kubeconfig (self-healing) |

## Validation (lint layer)

| Target | Purpose |
|---|---|
| `validate` | All basic syntax + connectivity checks |
| `validate-terraform-all` | terraform fmt+validate+tflint across all modules |
| `validate-terraform-tests` | `terraform test` (.tftest.hcl, requires TF >= 1.7) |
| `validate-ansible` | Syntax-check critical playbooks |
| `validate-ansible-structure` | Confirm every role has `molecule/default/` |
| `validate-yaml-lint` | yamllint + ansible-lint |
| `validate-shellcheck` | shellcheck on shell scripts |
| `validate-k8s-all` | kustomize build + kubeconform on every overlay |
| `validate-k8s-policies` | Conftest on `k8s/policies/*.rego` |
| `validate-k8s-policies-critical` | Blocking subset (CI gate) |
| `validate-sops-workflow` | Confirms encrypted files where required |
| `lint-workflows` | actionlint + zizmor on `.github/workflows/` |

## Tests

| Target | Purpose |
|---|---|
| `test-connectivity` | SSM connectivity to k3s server (Zero Trust) |
| `dry-run` | Full deployment plan dry-run |
| `dry-run-terraform` / `dry-run-ansible-cluster` / `dry-run-ansible-apps` | Per-layer dry-runs |
| `test-integration-localstack` | LocalStack: terraform apply + schema, tear down |
| `test-rpi` | Full validation suite for Raspberry Pi cluster |
| `test-rpi-prereqs` / `test-rpi-connectivity` / `test-rpi-ansible` / `test-rpi-full` | Per-step RPi tests |
| `new-role ROLE=name` | Scaffold new Ansible role from `.template` |
| `test-molecule` | All Molecule role test suites |
| `test-molecule-{role}` | Per-role: argocd, k3s, tailscale, gatekeeper, rpi, emergency-recovery |
| `test-molecule-arm64` | QEMU-based ARM64 matrix |
| `test-molecule-lint` | ansible-lint + yamllint across all Ansible files |
| `smoke-test` | Post-deploy smoke (16 apps × HTTP checks) |
| `test-e2e-post-deploy` | 40+ Bats cases covering connectivity + sync state |
| `test-contracts` | App-of-Apps path contracts + SOPS structure (offline) |
| `test-terraform` | Terraform validation tests |
| `test-security` | Security guardrails (SOPS, RBAC, secret leakage) |
| `test-security-supply-chain` | Image SBOM + vulnerability scan |
| `test-sops` | All expected SOPS files exist + decrypt |
| `test-acl-json` | Tailscale ACL validation |
| `test-dr` / `test-dr-execution` | Disaster recovery |
| `test-python` | Python unit tests + coverage gate (≥70%) |
| `test-python-coverage` | HTML report at `htmlcov/index.html` |
| `test-performance` | Benchmarks vs `.benchmarks/baseline.json` |
| `performance-baseline` | Save current as baseline |

Detail: [`../operations/testing.md`](../operations/testing.md).

## CI Setup (used by .github/workflows)

| Target | Purpose |
|---|---|
| `setup-ci-deps-all` | Install ALL CI deps (Makefile is source of truth for CI) |
| `setup-ci-deps-{tool}` | Per-tool: terraform, ansible, kubernetes, yamllint, shellcheck, kind, molecule, bats, python, workflow-lint, kustomize, kubeconform, age, conftest |

## QA Reporting

| Target | Purpose |
|---|---|
| `qa-audit` | Test execution audit (durations, skips) |
| `qa-scorecard` | Coverage + lint + security findings → `qa-scorecard.md` |
| `qa-verify-required-no-skips` | Fail if a required test was skipped without justification |

## Cost / Cleanup

| Target | Purpose |
|---|---|
| `show-costs` | Infracost estimates |
| `rollback-tf-refresh` | Refresh Terraform state for rollback |
| `rollback-argocd-status` | ArgoCD application status pre-rollback |
| `docs` | Print pointers to canonical docs |

---

## Related

- **Terraform operations:** [`../operations/terraform.md`](../operations/terraform.md)
- **Ansible operations:** [`../operations/ansible.md`](../operations/ansible.md)
- **Testing:** [`../operations/testing.md`](../operations/testing.md)
- **Cost detail:** [`../operations/cost-and-scheduling.md`](../operations/cost-and-scheduling.md)
