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

### A. Pay (immediate unblock)

Go to <https://github.com/settings/billing> → *Plans and usage* → *GitHub Actions* → set a spending limit > $0 (overage billing kicks in). New runs allocate within minutes.

### B. Wait for monthly reset (free, but slow)

Free-tier Actions minutes reset on the 1st of each month. Until then, **no GitHub-hosted runs**. Use Option C in parallel to keep landing low-risk PRs.

### C. Self-hosted runner on the Pi-4 (free, light jobs only)

Deploy the `github_runner` role on rasp-pi-04. See [`ansible/roles/github_runner/README.md`](../../ansible/roles/github_runner/README.md). Steps after the SOPS secret is created:

```bash
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml --tags github_runner --diff
```

Verify <https://github.com/ariel-extending851/homelab/settings/actions/runners> shows `rasp-pi-04-runner` with status **Idle** before merging any PR that touches the redirected jobs in `.github/workflows/ci-validation.yml`. GitHub Actions does **not** auto-fallback: a `runs-on: [self-hosted, arm64, pi-homelab]` job queues indefinitely (24h expiry) if no matching runner is online.

The 5 jobs currently redirected to the self-hosted tier are light enough for the Pi-4: `yaml-lint`, `python-tests-collect`, `sops-validation`, `lint-workflows`, `shellcheck`. Heavy jobs (`molecule`, `k3d-convergence`, `kubernetes-dry-run`, `disaster-recovery-execution`, `arm64-validation`, `integration-localstack`, terraform tests, trivy-image-scan) cannot run on a Pi-4 alongside k3s and remain on `ubuntu-latest`. Until A or B is resolved, Pipeline Gate stays red on every PR — the self-hosted tier only unblocks visual signal for the light tier.

### Pausing the runner for media playback

Pi-4 also runs Jellyfin. The role drops `CPUQuota=50%` + `MemoryMax=1G` + `Nice=15` + idle I/O class so the runner cannot starve transcoding. For a movie night where you want zero competition, pause completely:

```bash
ssh ubuntu@192.168.8.11 \
  'sudo systemctl stop actions.runner.ariel-extending851-homelab.rasp-pi-04-runner.service'
```

Re-enable with `systemctl start ...`. State flips to `Offline` / `Idle` in the GitHub runners UI.

### Removing the runner entirely (when GitHub-hosted comes back)

```bash
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml \
    --tags github_runner,uninstall \
    --extra-vars github_runner_uninstall=true --diff
```

Then revert the 5 `runs-on: [self-hosted, arm64, pi-homelab]` lines in `.github/workflows/ci-validation.yml` back to `runs-on: ubuntu-latest` in the same commit — otherwise those jobs queue forever.

## Why we hit this

Account: `ariel-extending851`. The homelab repo is private; private repos consume Actions minutes from the personal account's free-tier monthly allotment. Heavy PRs (e.g. PR #134 +9675/-882 across 190 files retried 4× over 16 hours on 2026-06-04/05) burn through the quota disproportionately because each job retry allocates a full VM.

Preventive measures (to add separately):

- A spending limit > $0 with email alert at 75 % usage.
- Workflow concurrency caps stricter than `cancel-in-progress: true` (already set) — e.g. one rule per branch *and* per workflow.
- Move long-tail jobs (Trivy daily image scan, nightly-e2e) to a self-hosted tier so they don't compete for the same minute budget.

## Related

- [`feedback_ansible_sops_plugin.md`](../../memory/feedback_ansible_sops_plugin.md) (auto-memory) — `.sops.yml` extension requirement for the SOPS secret in Option C.
- [`ansible/roles/github_runner/`](../../ansible/roles/github_runner/) — the role implementation.
