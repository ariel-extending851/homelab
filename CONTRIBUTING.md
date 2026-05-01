# Contributing

Thanks for considering a contribution. This file covers the development workflow. For detailed Ansible role authoring, see [`docs/contributing/ansible-roles.md`](docs/contributing/ansible-roles.md).

## Development Workflow

### 1. Create a branch

```bash
git checkout -b <type>/<short-description>
```

Conventional commit-style prefixes: `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`, `ci/`.

### 2. Make changes

Follow the conventions in [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md):

- Resource names: `hl-` prefix, kebab-case
- Filenames: kebab-case
- Versions: semver
- Doc style: see [`docs/contributing/doc-style.md`](docs/contributing/doc-style.md)

### 3. Test locally before pushing

```bash
# Lint everything that changed
make validate-yaml-lint
make validate-shellcheck
make validate-terraform-all
make validate-k8s-all

# Per-area tests
make test-python                  # if you touched Python (Lambda, scheduler, inventory)
make test-molecule-<role>         # if you touched an Ansible role
make test-terraform               # if you touched Terraform
make validate-k8s-policies        # if you touched K8s manifests
```

The full test layer breakdown is in [`docs/operations/testing.md`](docs/operations/testing.md).

### 4. Commit

Use signed commits where possible. Conventional Commits format encouraged:

```text

Closes #123
```

### 5. Push and open a PR

CI runs validation across 13 parallel jobs (terraform, kubeconform, conftest, molecule, molecule-arm64, etc.). All required jobs must pass; the `pipeline-gate` job aggregates them.

For Ansible roles, the `enforce-molecule-tests` job rejects PRs adding a role without `molecule/default/`.

### 6. Address review comments

Push fixes as new commits (don't rebase mid-review unless asked). Squash on merge.

## Adding an Ansible Role

Every Ansible role **must** have Molecule tests. CI enforces this.

```bash
make new-role ROLE=my_role          # scaffolds from templates/ansible-role/ via Copier
make new-app  APP=my-app            # scaffolds a k8s app from templates/k8s-app/ via Copier
```

Then follow the checklist in [`docs/contributing/role-template.md`](docs/contributing/role-template.md) and the full guide in [`docs/contributing/ansible-roles.md`](docs/contributing/ansible-roles.md).

## Editing Documentation

- New doc → use the templates in [`docs/contributing/doc-style.md`](docs/contributing/doc-style.md)
- Move/rename a doc → update all referrers; CI's Lychee link checker catches misses
- Add a new ingress hostname → also update [`docs/reference/tailnet-services.md`](docs/reference/tailnet-services.md)
- Significant security or architecture change → add an entry to [`docs/security/audit-history.md`](docs/security/audit-history.md)

## Editing Secrets

Use SOPS — see [`docs/operations/sops-setup.md`](docs/operations/sops-setup.md). Never commit unencrypted secrets; pre-commit and CI both reject them.

## Reporting Issues

Open a GitHub issue at <https://github.com/ariel-extending851/homelab/issues> with:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Output of `kubectl get nodes`, `kubectl get applications -n argocd` if cluster-related

## Questions

Look in [`docs/`](docs/) first — most things are documented there. If a doc is missing or wrong, that's also a valid PR.
