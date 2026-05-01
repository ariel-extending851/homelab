# GitHub Environments — Setup & Maintenance

The CD pipeline `.github/workflows/ci-deployment.yml` references three
GitHub Environments by name. **They must exist before the first push to
`main`** — otherwise the jobs run without their intended reviewers / wait
timers / branch restrictions, defeating the gate.

## Environments

| Name | Wait timer | Required reviewers | Branch policy | Purpose |
|---|---|---|---|---|
| `staging-deploy` | 0 | none | none | Ephemeral staging workspace; no human in the loop. |
| `production-approval` | 5 min | ≥1 (default: repo owner) | protected branches only (`main`) | Manual approval gate after staging passes. |
| `production` | 0 | none | protected branches only (`main`) | Runtime env for prod terraform-apply / ansible / rollback. Reviewer is upstream on `production-approval` to avoid double-prompts. |

## First-time setup

```bash
gh auth status                            # confirm you're authenticated as repo admin
python3 bin/setup_github_environments.py  # idempotent — safe to re-run
```

To require extra reviewers on `production-approval`:

```bash
python3 bin/setup_github_environments.py --reviewers alice,bob
```

## Verification

```bash
gh api "repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/environments"
```

Expect three environments listed; `production-approval` should show a
`wait_timer` rule (300s) and a `required_reviewers` rule with at least one
user.

## When to re-run

- Adding or rotating reviewers (pass `--reviewers …` and re-run).
- After repo transfer (environment configs are repo-scoped).
- If someone deleted an environment via the UI.

## Why this isn't Terraform-managed

The `integrations/github` Terraform provider needs an admin PAT, which
adds a credential to rotate. For a homelab, an idempotent shell script
invoked manually (or once during onboarding) is simpler. Revisit if we
add a second repo or scale beyond the current owner.
