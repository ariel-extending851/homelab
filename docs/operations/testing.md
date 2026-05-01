# Testing

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

The repo runs five layers of automated tests. Pick the layer that matches what you're changing.

| Layer | When to run | Speed | Money cost |
|---|---|---|---|
| Lint (yamllint, shellcheck, tflint, ansible-lint) | Every save | <30 s | $0 |
| Unit tests (pytest, tftest) | Per-module changes | ~30 s | $0 |
| Molecule (Ansible role tests in Docker) | Role changes | 2–5 min | $0 |
| LocalStack (Terraform plan against fake AWS) | Infra changes | 5–10 min | $0 |
| Real AWS (smoke + E2E post-deploy) | Pre-merge or after `terraform apply` | 10–20 min | ~$0.10 |

CI runs all layers except the last (which fires on `main` push only — see [`.github/workflows/ci-deployment.yml`](../../.github/workflows/ci-deployment.yml)).

---

## Where tests live

| Test kind | Location |
|---|---|
| Python unit / contract tests for any script in the repo | [`bin/tests/`](../../bin/tests/) (pytest + Bats) — single home, regardless of which top-level dir the script under test lives in |
| Shared pytest config and `conftest.py` | [`bin/tests/conftest.py`](../../bin/tests/conftest.py) |
| Terraform native tests (`*.tftest.hcl`) | [`infra/aws/tests/`](../../infra/aws/tests/), [`infra/aws-oidc/tests/`](../../infra/aws-oidc/tests/) — kept next to the module they test |
| Ansible role tests (Molecule) | `ansible/roles/<role>/molecule/default/` — co-located with the role by Molecule's design |
| Lambda package tests | [`infra/aws/modules/scheduler/lambda_src/tests/`](../../infra/aws/modules/scheduler/lambda_src/tests/) — **exception** to the `bin/tests/` rule because the Lambda is a self-contained Python package zipped and deployed as a unit |

Discovery is configured via `testpaths` in [`pyproject.toml`](../../pyproject.toml). Adding a new test file under `bin/tests/test_*.py` picks it up automatically.

---

## Prerequisites

All tools are pinned in [`.mise.toml`](../../.mise.toml). Install them once:

```bash
mise install
make setup-ci-deps-all     # verifies + installs anything missing (pytest-cov, boto3, etc.)
```

| Tool | Purpose |
|---|---|
| `terraform`, `tflint`, `sops`, `age`, `kubectl`, `kustomize`, `kubeconform` | Infra & K8s validation |
| `ansible-core`, `ansible-lint`, `molecule`, `community.aws`, `community.sops` | Ansible tests |
| `pytest`, `pytest-cov`, `pytest-benchmark` | Python unit + benchmark tests |
| `bats` | Bash test framework (smoke tests) |
| `localstack`, `terraform-local`, `awscli-local` | Offline AWS testing |
| `conftest` | OPA policy enforcement on K8s manifests |
| `actionlint`, `zizmor` | GitHub Actions linting / security |

---

## Lint Layer

```bash
make validate-yaml-lint            # yamllint + ansible-lint
make validate-shellcheck           # shell scripts
make validate-terraform-all        # terraform fmt -check, validate, tflint
make validate-k8s-all              # kustomize build + kubeconform on every overlay
make validate-k8s-policies         # Conftest against all policies in k8s/policies/
make validate-sops-workflow        # confirms encrypted files where required
```

`make lint-workflows` runs `actionlint` + `zizmor` on all GitHub Actions YAML.

---

## Unit / Module Tests

### Python (Lambda scheduler, Terraform inventory)

```bash
make test-python                   # all pytest, with coverage
make test-python-coverage          # HTML report at htmlcov/index.html
```

CI fails the build if total coverage drops below **70%**. Current coverage: scheduler Lambda 100%, Terraform inventory ~70%.

### Terraform unit tests (`.tftest.hcl`)

Lives in `infra/aws/tests/` and `infra/aws-oidc/tests/`. Native `terraform test` framework — no LocalStack needed for variable validation.

```bash
make test-terraform
# or directly:
cd infra/aws && terraform test
```

### Performance benchmarks

```bash
make test-performance              # runs benchmarks, fails if >10% regression vs baseline
make performance-baseline          # save current as new baseline (after intentional optimization)
```

Baseline lives in `.benchmarks/baseline.json` (git-tracked).

---

## Molecule (Ansible Role Tests)

Each role under [`ansible/roles/`](../../ansible/roles/) has a `molecule/default/` scenario that:

1. Spins up a Docker container playing the target OS
2. Runs the role
3. Verifies expected state (idempotency check on second run, custom verifiers in `verify.yml`)

CI gate: every role must have `molecule/default/` (enforced by `enforce-molecule-tests` job in `ci-validation.yml`).

### Run all roles

```bash
make test-molecule
```

### Run one role

```bash
make test-molecule-k3s
make test-molecule-argocd
make test-molecule-rpi
make test-molecule-tailscale
make test-molecule-gatekeeper
make test-molecule-emergency-recovery
```

### Run all roles on ARM64 (QEMU emulation)

```bash
make test-molecule-arm64
```

This uses `docker/setup-qemu-action`-equivalent locally. Slow (45 min in CI), but catches Pi-only regressions.

### Validate Ansible structure

```bash
make validate-ansible-structure    # confirms every role has molecule/default/
make new-role ROLE=myrole          # scaffold from templates/ansible-role/ (Copier)
```

---

## LocalStack (Terraform without AWS)

LocalStack mocks AWS APIs. Use it to validate Terraform module structure, variable behavior, and resource graphs **without spending money or needing AWS credentials**.

### What LocalStack covers

| Component | Coverage |
|---|---|
| Terraform syntax + module structure | ✅ Full |
| Variable validation | ✅ Full |
| Resource dependency graph | ✅ Full |
| SOPS provider integration (with mock secrets) | ✅ Full |
| Output formatting | ✅ Full |
| Provider configuration | ✅ Full |

### What LocalStack does NOT cover

| Component | Why | Alternative |
|---|---|---|
| EC2 spot instance behavior | Not supported | AWS Free Tier or real apply |
| User-data execution (k3s install) | LocalStack doesn't run user data | SSH to a real instance |
| IAM permission enforcement | Limited IAM | Real apply + integration tests |
| Network reachability (SG rules) | SGs not enforced | Real apply |

### Quick start

```bash
# Use the version pinned in .mise.toml (single source of truth)
LOCALSTACK_VERSION=$(awk -F'"' '/^localstack/ {print $2; exit}' .mise.toml)
docker run -d --name localstack -p 4566:4566 -e SERVICES=ec2,iam,ssm \
  localstack/localstack:"${LOCALSTACK_VERSION}"
sleep 15
cd infra/aws
python3 scripts/validate_localstack.py
```

The wrapper:
1. Copies `provider.localstack.tf.example` → `provider_override.tf`
2. Runs `terraform init -reconfigure`
3. Runs `terraform validate` and `terraform plan -var-file=terraform.tfvars.localstack`
4. Counts resources in plan, asserts module composition

Expected results: 6/7 tests pass, 13 resources in plan, 2 modules loaded (`compute`, `network`).

### Manual workflow

```bash
cp infra/aws/testing/provider.localstack.tf.example infra/aws/provider_override.tf
cd infra/aws
terraform init -reconfigure
terraform validate
terraform plan -var-file=testing/terraform.tfvars.localstack

# cleanup
rm provider_override.tf
docker stop localstack
```

---

## Real AWS — Smoke & E2E

After `terraform apply` + `make ansible-deploy`, run the post-deployment checks.

### Smoke test (~2 min)

```bash
make smoke-test
```

### E2E post-deploy (~10 min)

```bash
make test-e2e-post-deploy
```

### Observability gate (~3 min)

ArgoCD `Synced + Healthy` is necessary but not sufficient — a pod can flap into CrashLoopBackOff seconds after sync, or a Deployment can satisfy `availableReplicas` while a sidecar is OOMing. The observability gate runs *after* `validate-argocd-synced` and queries Prometheus directly for the silent-failure signals:

- `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`
- `kube_deployment_status_replicas_unavailable`
- `kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}`

```bash
# CI port-forwards Prometheus first; locally do the same:
kubectl port-forward -n prometheus svc/prometheus 9090:9090 &
PROMETHEUS_URL=http://localhost:9090 OBSERVATION_WINDOW=300 \
  python3 bin/post_deploy_observability_gate.py
```

Source: [`bin/post_deploy_observability_gate.py`](../../bin/post_deploy_observability_gate.py). Exit non-zero blocks the deploy in `ci-deployment.yml`.

### Velero restore drill (~5 min)

```bash
make test-velero-restore   # backup → delete → restore → integrity check
```

Full procedure: [`backup-and-restore.md`](backup-and-restore.md).

### Ansible idempotency (~3–6 min)

```bash
make test-ansible-idempotency
```

Runs `site.yml` twice and asserts the second run is fully idempotent (zero `changed` tasks). Backed by [`bin/check_molecule_idempotence.py`](../../bin/check_molecule_idempotence.py); also runs at the end of every Molecule scenario.

### Other verification targets

```bash
make test-rpi                      # RPi-specific node validation
make test-security                 # secret leakage, RBAC wildcards
make test-security-supply-chain    # image SBOM + vuln scan
make test-sops                     # all expected SOPS files exist + decrypt
make test-acl-json                 # Tailscale ACL validation
make test-contracts                # AWS CLI contract tests in bin/tests/contracts/
make test-dr-execution             # disaster recovery scenario
```

### ArgoCD sync wait

```bash
make validate-argocd-synced        # blocks until apps-root is Synced + Healthy
```

Used by CI deployment to gate post-deploy tests.

---

## CI Integration

### `.github/workflows/ci-validation.yml` (every PR)

Runs in 13 parallel jobs, each with its own mise cache:

- terraform validate + tests
- yamllint + kubeconform
- shellcheck
- ansible-lint
- molecule (per role)
- molecule-arm64 (QEMU matrix)
- python unit tests + coverage gate
- python benchmarks (regression check)
- conftest policies
- workflow linting (actionlint, zizmor)

Cache key per-job: `mise-<job>-${{ hashFiles('.mise.toml') }}` with fallbacks. First run ~5 min; cached runs ~10–15 s for setup.

### `.github/workflows/ci-deployment.yml` (push to `main`)

Calls Makefile targets (no inline shell):
1. `terraform-apply`
2. `ansible-deploy`
3. `validate-argocd-synced`
4. `smoke-test`
5. `test-e2e-post-deploy`
6. Rollback playbook on failure (`rollback-tf-refresh`, `rollback-argocd-status`)

This means **`make terraform-apply` locally is identical to CI** — Makefile is the single source of truth.

---

## QA Scorecard

```bash
make qa-scorecard                  # produces qa-scorecard.md with coverage, lint pass rates, security findings
make qa-audit                      # detailed test execution audit (which tests skipped, durations)
make qa-verify-required-no-skips   # fails if a required test was skipped without justification
```

---

## Checklist Before Merging Infrastructure Changes

- [ ] `make validate-terraform-all` passes
- [ ] `make test-terraform` passes
- [ ] `make test-molecule` passes for any role you touched
- [ ] LocalStack plan succeeds (`python3 infra/aws/scripts/validate_localstack.py`)
- [ ] If touching a Lambda or scheduler: `make test-python` ≥ 70% coverage, no benchmark regression
- [ ] If touching K8s manifests: `make validate-k8s-all` + `make validate-k8s-policies-critical`
- [ ] If touching SOPS rules: `make test-sops` and `make validate-sops-workflow`
- [ ] After deploy: `make smoke-test` returns 0

---

## Related

- **Terraform operations:** [`terraform.md`](terraform.md)
- **Ansible operations:** [`ansible.md`](ansible.md)
- **SOPS workflow:** [`sops-setup.md`](sops-setup.md)
- **Per-app health checks:** the relevant doc under [`../services/`](../services/)
