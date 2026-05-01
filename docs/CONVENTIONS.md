# Conventions

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Naming, versioning, and documentation conventions for the homelab project. Adherence ensures consistency and discoverability for a single maintainer.

---

## 1. Resource Naming

All resources created for or by this project use the `hl-` prefix and `kebab-case`.

### 1.1 Prefix rule

All project-related resources MUST be prefixed with `hl-`. The prefix groups and filters resources, especially in cloud environments.

### 1.2 Case style

All resource names MUST use `kebab-case`: lowercase letters with words separated by hyphens.

### 1.3 Examples

- **Cloud resources:** `hl-k3s-control-plane-01`, `hl-main-vpc`, `hl-public-subnet`
- **Kubernetes resources:** `hl-argocd`, `hl-monitoring`. The `hl-` prefix may be omitted for application-specific resources within a dedicated, project-scoped namespace.
- **Git repositories:** `hl-k8s-manifests`, `hl-infra-provisioning`

---

## 2. Versioning (SemVer)

All versioned artifacts use Semantic Versioning: `MAJOR.MINOR.PATCH` (e.g., `v1.2.3`).

- **MAJOR** — incompatible API changes
- **MINOR** — backwards-compatible functionality
- **PATCH** — backwards-compatible bug fixes

Examples: container image tags `ghcr.io/your-user/hl-webapp:v1.0.0`; Terraform module pinning `source = "./modules/vpc?ref=v1.2.0"`.

---

## 3. Documentation File Naming

- **Filenames:** `kebab-case.md` (e.g., `control-plane-recovery.md`, not `CRITICAL-RECOVERY-PLAN.md`)
- **Index files:** `README.md` inside any directory acts as its index

---

## 4. Markdown Style

- **Headings:** ATX-style (`#`, `##`); one H1 per file (the title); never skip levels
- **Code blocks:** triple backticks with a language hint (`bash`, `yaml`, `hcl`, `mermaid`, `python`)
- **Links:** relative paths for internal references; absolute `https://` for external
- **Tables:** GitHub-flavored Markdown; left-aligned by default

---

## 5. Document Header Template

Every document starts with this header (no YAML frontmatter — no static site generator consumes it):

```markdown
# <Title>

> **Status:** Active | Draft | Deprecated
> **Last reviewed:** YYYY-MM-DD
> **Owner:** @ariel-extending851

<one-sentence purpose statement>

---
```

Specialized templates for runbooks and service docs live in [`contributing/doc-style.md`](contributing/doc-style.md).

---

## 6. Directory Layout

### 6.1 Documentation tree

The canonical doc tree is described in [`docs/README.md`](README.md). New documents go into the appropriate bucket: `getting-started/`, `architecture/`, `operations/`, `services/`, `runbooks/`, `security/`, `contributing/`, `reference/`, `plans/`. Anything no longer maintained moves to `archive/` (excluded from CI link-checking).

### 6.2 Code & test placement

| Kind | Location | Notes |
|---|---|---|
| Python tests (unit, contract, e2e) | `bin/tests/test_<script>.py`, `bin/tests/*.bats` | One pytest config (`pyproject.toml` `testpaths`); shared `conftest.py` lives here. |
| Python CLI / orchestrator scripts | `bin/*.py` | Main entry points invoked from Makefile or CI. |
| Domain-specific Python helpers | `ansible/*.py`, `ansible/scripts/*.py`, `infra/aws/scripts/*.py` | Helpers tightly coupled to a tool's working tree (dynamic inventory, LocalStack validators, etc.). Their tests still live in `bin/tests/`. |
| Ansible roles | `ansible/roles/<name>/` | Each role MUST include `molecule/default/` co-located with the role — see [`contributing/ansible-roles.md`](contributing/ansible-roles.md). |
| Ansible playbooks | `ansible/playbooks/` | Subdirs `gitops/`, `maintenance/`, `recovery/` for grouping. |
| Terraform modules | `infra/aws/modules/<name>/` | Self-contained units. |
| Terraform native tests | `infra/aws/tests/*.tftest.hcl`, `infra/aws-oidc/tests/*.tftest.hcl` | Use the `terraform test` framework, not pytest. |
| Lambda packages | `infra/aws/modules/<module>/lambda_src/` with co-located `tests/` | **Exception** to the `bin/tests/` rule: Lambda is a self-contained Python package zipped and deployed as a unit, so tests live next to the code being packaged. |
| Kubernetes app manifests | `k8s/apps/<app>/` | Folder name matches namespace. |
| OPA / Conftest policies | `k8s/policies/*.rego` | |
| Shell scripts | Avoid. | Prefer Python; existing shell logic was migrated in commit `9eecfcc`. |
