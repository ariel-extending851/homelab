# Runbook: GitHub Actions runner quota exhausted

| Field | Value |
|:--- |:--- |
| **Severity** | 🟡 Warning (CI red across the board; no code outage) |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-06-06 |
| **Owner** | @ariel-extending851 |

---

## Symptoms

Every workflow job (CI Validation, Docs, Checkov, Claude Code Review, scheduled drift-detection, manually-dispatched runs) fails in **3–5 seconds** with no logs visible in the UI. `gh run view <id> --json jobs` shows every entry as `failure` with `steps: []`. Repeated re-runs at the same SHA reproduce identically, including across different workflow files.

Critical tell: a successful run at SHA `X` is followed by failures at the same SHA `X` later (push event = success, schedule event seconds later = failure). The code didn't change — the environment did.

## How to confirm it's the runner quota and not workflow code

1. Trigger a fresh run on develop so you have non-expired logs (GitHub blob retention is short):
   ```bash
   gh workflow run ci-validation.yml --ref develop
   sleep 30
   gh run list --branch develop --workflow ci-validation.yml --limit 1 \
     --json databaseId,status,conclusion
   ```
2. Download the full log zip via the REST endpoint (the per-job `/logs` endpoint returns `BlobNotFound` for jobs that never produced step output):
   ```bash
   RUN=$(gh run list --branch develop -L 1 --json databaseId --jq '.[].databaseId')
   curl -sL -H "Authorization: token $(gh auth token)" \
     -H "Accept: application/vnd.github+json" \
     "https://api.github.com/repos/ariel-extending851/homelab/actions/runs/$RUN/logs" \
     -o /tmp/run_logs.zip
   unzip -p /tmp/run_logs.zip "*/system.txt" | tail -3
   ```
3. The terminal line in every `system.txt` is the diagnostic:
   ```text
   Job is about to start running on the hosted runner: GitHub Actions <runner_id>
   Job is waiting for a hosted runner to come online.
   ```
   That last line is the symptom: GitHub assigned a runner ID, then never provisioned the underlying VM. Most common cause for private repos is **exhausted Actions minute quota on the billing account**.
4. Confirm the symptom is account-wide (not workflow-specific) by checking a different workflow at a similar timestamp:
   ```bash
   gh run list --workflow docs.yml -L 1 --json databaseId --jq '.[].databaseId' \
     | xargs -I{} curl -sL -H "Authorization: token $(gh auth token)" \
       "https://api.github.com/repos/ariel-extending851/homelab/actions/runs/{}/logs" \
       -o /tmp/docs.zip && unzip -p /tmp/docs.zip "*/system.txt" | tail -1
   ```
   Same final line confirms it's not a `ci-validation.yml` bug.

## Recovery (pick one)

### Option A — Docker compose runner on pc-tower (preferred, free, currently deployed)

Lightest path when a host with Docker is available. The pc-tower (Bluefin / Fedora x86_64, 12c / 15G) hosts the runner as a long-lived container via `ci/runner/docker-compose.yml`; the `make runner-up` target reads the PAT from the SOPS-encrypted group_vars file and starts it. See [`ci/runner/README.md`](../../ci/runner/README.md).

```bash
make runner-up      # start + register
make runner-status  # ps + GitHub-side registration
make runner-logs    # tail
make runner-down    # stop without deleting cache volume
make runner-reset   # also drop the persistent work cache
```

The runner registers as `pc-tower-runner` with labels `self-hosted, X64, pc-homelab`. Verify Idle at <https://github.com/ariel-extending851/homelab/settings/actions/runners>.

**Coverage today:** the workflow redirects only the 5 light jobs (`yaml-lint`, `python-tests-collect`, `sops-validation`, `lint-workflows`, `shellcheck`) to `runs-on: [self-hosted, pc-homelab]`. Heavy jobs (`molecule`, `k3d-convergence`, `kubernetes-dry-run`, `disaster-recovery-execution`, `arm64-validation`, `integration-localstack`, `trivy-image-scan`, terraform set) still target `ubuntu-latest` and remain red until billing returns. pc-tower has the raw capacity for them (12c/15G + Docker socket access for sibling containers) — peel them over one at a time as compatibility is verified.

**Pausing for foreground work** (movies, gaming, build of your own code):

```bash
make runner-down   # instantaneous; in-flight jobs are killed
make runner-up     # back online in ~30 s
```

State flips between `Offline` and `Idle` in the GitHub runners UI.

**Full decommission when GitHub-hosted minutes come back:**

```bash
make runner-reset                                # stop + clear work volume
# revert the 5 `runs-on: [self-hosted, pc-homelab]` lines in
# .github/workflows/ci-validation.yml back to `runs-on: ubuntu-latest`
```

### Option B — Pay for GitHub-hosted minutes

<https://github.com/settings/billing> → *Plans and usage* → *GitHub Actions* → set a spending limit > $0. New runs allocate within minutes.

### Option C — Wait for monthly reset

Free-tier Actions minutes reset on the 1st of each month. Until then, no GitHub-hosted runs. Keep Option A active in parallel so the light tier stays green.

### Option D — Ansible/systemd runner on another host (Pi or Fedora workstation)

For hosts without Docker (Raspberry Pi) or where systemd unit management is preferable to a container, the `ansible/roles/github_runner/` role installs and registers the runner as a `actions.runner.*` systemd unit. Distro-aware (`apt`/`dnf`), arch-detected (`arm64`/`x64`). See [`ansible/roles/github_runner/README.md`](../../ansible/roles/github_runner/README.md). Add the host to the `github_runners` group in `ansible/inventory/production.yml` first.

## Why we hit this

Account: `ariel-extending851`. The homelab repo is private; private repos consume Actions minutes from the personal account's free-tier monthly allotment. Heavy PRs (e.g. PR #134 +9675/-882 across 190 files retried 4× over 16 hours on 2026-06-04/05) burn through the quota disproportionately because each job retry allocates a full VM.

Preventive measures (to add separately):

- A spending limit > $0 with email alert at 75 % usage.
- Workflow concurrency caps stricter than `cancel-in-progress: true` (already set) — e.g. one rule per branch *and* per workflow.
- Move long-tail jobs (Trivy daily image scan, nightly-e2e) to a self-hosted tier so they don't compete for the same minute budget.

## Related

- [`feedback_ansible_sops_plugin.md`](../../memory/feedback_ansible_sops_plugin.md) (auto-memory) — `.sops.yml` extension requirement for the SOPS secret in Option C.
- [`ansible/roles/github_runner/`](../../ansible/roles/github_runner/) — the role implementation.
