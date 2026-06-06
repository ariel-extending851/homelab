# Role: `github_runner`

Install + register a GitHub Actions self-hosted runner as a systemd service on a Linux host. Distro-aware (Debian/Ubuntu via `apt`, Fedora/RHEL via `dnf`); arch auto-detected from `ansible_architecture` (`aarch64` → `arm64`, otherwise `x64`).

Created to unblock CI when the org's GitHub-hosted runner minute quota is exhausted on a private repo. Five light CI jobs (`yaml-lint`, `lint-workflows`, `shellcheck`, `python-tests-collect`, `sops-validation`) plus the heavy ones (`molecule`, `k3d-convergence`, `kubernetes-dry-run`, `disaster-recovery-execution`, `trivy-image-scan`, terraform tests) all redirect to `runs-on: [self-hosted, pc-homelab]` in `.github/workflows/ci-validation.yml` and run on pc-tower.

## Inventory wiring

The role targets the `github_runners` Ansible group in `ansible/inventory/production.yml`. Currently `pc-tower` only (Fedora Bluefin, 12 cores, 15 GB RAM). The Pi-4 is excluded because (a) the role auto-uninstall path was used to clear an earlier deployment and (b) Pi-4 contends with Jellyfin transcoding on the same host.

Host-specific overrides live in `ansible/host_vars/<hostname>.yml`. pc-tower widens `github_runner_cpu_quota` (50 % → 600 %, i.e. 6 of 12 cores) and `github_runner_memory_max` (1 GB → 8 GB) so heavy jobs fit.

## Secrets

Long-lived GitHub PAT (used to exchange for short-lived registration tokens) lives in `ansible/group_vars/github_runners.sops.yml`. See the `.example` file in `ansible/group_vars/` for required scopes. Fine-grained PAT (Administration RW + Metadata R on the homelab repo) is the canonical choice; a classic PAT with `repo` scope also works.

The file **MUST** end in `.sops.yml`, not `.sops.yaml` — the `community.sops` vars plugin matches `.sops.yml` only and silently ignores `.yaml`. This is auto-memory `feedback_ansible_sops_plugin.md`.

The `.sops.yaml` config has a dedicated creation rule for `github_runners.sops.yml` so `github_runner_pat` is encrypted (the broader group_vars catch-all rule only matches `wifi_password`).

## First-time setup

Pre-req on the host: sshd enabled and accessible from wherever you run ansible-playbook (in the homelab case, the DevContainer reaches pc-tower via the host's primary interface).

```bash
# 1. Create the SOPS secret (one-time)
cp ansible/group_vars/github_runners.sops.yml.example /tmp/gh.yml
vim /tmp/gh.yml   # paste fine-grained PAT
mise exec -- sops -e --filename-override ansible/group_vars/github_runners.sops.yml /tmp/gh.yml \
  > ansible/group_vars/github_runners.sops.yml
shred -u /tmp/gh.yml

# 2. Run the playbook from the ansible/ directory (SOPS plugin requirement)
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml --tags github_runner --diff

# 3. Verify on the host
ssh agfonseca@192.168.8.120 'sudo systemctl status actions.runner.ariel-extending851-homelab.pc-tower-runner.service'
```

## Verification in GitHub UI

After successful registration, <https://github.com/ariel-extending851/homelab/settings/actions/runners> should list `pc-tower-runner` with labels `self-hosted, x64, pc-homelab` and status `Idle`.

## Local testing

```bash
make test-molecule-github_runner
```

The molecule scenario uses `github_runner_skip_download`, `github_runner_skip_register`, and `github_runner_skip_service_start` (set in `molecule/default/molecule.yml`) so the role's idempotent paths (user/group/dir creation, package install) are exercised without hitting `github.com`. Production playbooks leave all three flags `false`.

The verify step asserts `libicu-dev` (Debian-side); the Fedora-side `libicu` install path runs only in production.

## Token rotation

When the PAT expires:

```bash
sops ansible/group_vars/github_runners.sops.yml   # edit, save
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml --tags github_runner --diff
```

The role detects the runner is already registered and skips re-registration; the next runner-token exchange (forced by a label change or hostname change) will use the new PAT.

## Pausing without uninstalling

For interactive work where you want zero CPU/IO contention:

```bash
ssh agfonseca@192.168.8.120 \
  'sudo systemctl stop actions.runner.ariel-extending851-homelab.pc-tower-runner.service'

# Re-enable later
ssh agfonseca@192.168.8.120 \
  'sudo systemctl start actions.runner.ariel-extending851-homelab.pc-tower-runner.service'
```

Status: `systemctl status actions.runner.*` or the runners page above (state flips between `Idle` and `Offline`).

## Full uninstall

When you want the runner gone (GitHub-hosted minutes returned, decommissioning):

```bash
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml \
    --tags github_runner,uninstall \
    --extra-vars github_runner_uninstall=true \
    --diff
```

This stops the service, calls `config.sh remove` so the runner disappears from the GitHub UI, deletes the systemd unit + drop-in + install dir + `github-runner` user + group. `libicu(-dev)` and `mise` stay on the host (used elsewhere). Idempotent — a second run is a no-op.

After uninstall, **also revert the `runs-on: [self-hosted, pc-homelab]` lines in `.github/workflows/ci-validation.yml` back to `runs-on: ubuntu-latest`** — otherwise the affected jobs queue 24 h until they time out.

## Why not actions-runner-controller (ARC) in k8s?

Considered and rejected for this iteration: ARC requires cert-manager + a webhook + RunnerSet CRDs + a Helm chart pin. systemd on a single host is one role + one secret + zero new dependencies. If the runner fleet grows to >3 instances or ephemeral-per-job becomes a requirement, revisit ARC.

## Testing

Run Molecule tests locally:

```bash
make test-molecule-github_runner
```

See [`docs/operations/testing.md`](../../../docs/operations/testing.md) for the full testing guide and [`docs/contributing/role-template.md`](../../../docs/contributing/role-template.md) for the new-role checklist.
