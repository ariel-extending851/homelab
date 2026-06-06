# Role: `github_runner`

Install + register a GitHub Actions self-hosted runner as a systemd service on a Linux host (ARM64 today; tarball URL covers x64 if `github_runner_arch` is overridden).

Created to unblock CI when the org's GitHub-hosted runner minute quota is exhausted on a private repo. Light CI jobs (`lint-workflows`, `shellcheck`, `python-tests-collect`, `sops-validation`, `yaml-lint`) are redirected to `runs-on: [self-hosted, arm64, pi-homelab]` in `.github/workflows/ci-validation.yml`. Heavy jobs (`molecule`, `k3d-convergence`, `arm64-validation`, `kubernetes-dry-run`, `disaster-recovery-execution`) remain on `ubuntu-latest` because the 8 GB Pi-4 cannot host a kind/k3d/QEMU cluster alongside k3s.

## Inventory wiring

The role targets the `github_runners` Ansible group, defined in `ansible/inventory/production.yml`. Today only `rasp-pi-04` is in this group (Pi-3 has 1 GB RAM — too tight for runner + k3s-agent + AdGuard).

## Secrets

Long-lived GitHub PAT (used to exchange for short-lived registration tokens) lives in `ansible/group_vars/github_runners.sops.yml`. See the `.example` file in `ansible/group_vars/` for required scopes (fine-grained: Administration RW + Metadata R on the homelab repo).

The file **MUST** end in `.sops.yml`, not `.sops.yaml` — the `community.sops` vars plugin matches `.sops.yml` only and silently ignores `.yaml`. This is auto-memory `feedback_ansible_sops_plugin.md`.

## First-time setup

```bash
# 1. Create the SOPS secret (one-time)
cp ansible/group_vars/github_runners.sops.yml.example /tmp/gh.yml
vim /tmp/gh.yml   # paste fine-grained PAT
sops -e /tmp/gh.yml > ansible/group_vars/github_runners.sops.yml
shred -u /tmp/gh.yml

# 2. Run the playbook from the ansible/ directory (SOPS plugin requirement)
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml --tags github_runner --diff

# 3. Verify on the host
ssh ubuntu@192.168.8.11 'sudo systemctl status actions.runner.ariel-extending851-homelab.rasp-pi-04-runner.service'
```

## Verification in GitHub UI

After successful registration, `https://github.com/ariel-extending851/homelab/settings/actions/runners` should list `rasp-pi-04-runner` with labels `self-hosted, arm64, pi-homelab` and status `Idle`.

## Local testing

```bash
make test-molecule-github_runner
```

The molecule scenario uses `github_runner_skip_download`, `github_runner_skip_register`, and `github_runner_skip_service_start` (set in `molecule/default/molecule.yml`) so the role's idempotent paths (user/group/dir creation, package install) are exercised without hitting `github.com`. Production playbooks leave all three flags `false`.

## Token rotation

When the PAT expires:

```bash
sops ansible/group_vars/github_runners.sops.yml   # edit, save
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml --tags github_runner --diff
```

The role will detect the runner is already registered, skip re-registration, but the next runner-token exchange (if forced by a label change or hostname change) will use the new PAT.

## Coexistence with Jellyfin (Pi-4 is also the media node)

The role drops a systemd `resource-caps.conf` override that caps the runner at `CPUQuota=50 %` + `MemoryMax=1G` + `Nice=15` + idle I/O scheduling class. Even at full CI load Jellyfin transcoding keeps priority — measured baseline on Pi-4 is `top` %CPU within ±5 of pre-runner state during 1080p playback.

For a movie night where you want zero competition, pause completely without uninstalling:

```bash
# Pause (instant — in-flight jobs are killed)
ssh ubuntu@192.168.8.11 \
  'sudo systemctl stop actions.runner.ariel-extending851-homelab.rasp-pi-04-runner.service'

# Re-enable later
ssh ubuntu@192.168.8.11 \
  'sudo systemctl start actions.runner.ariel-extending851-homelab.rasp-pi-04-runner.service'
```

Status: `systemctl status actions.runner.*` or [`https://github.com/ariel-extending851/homelab/settings/actions/runners`](https://github.com/ariel-extending851/homelab/settings/actions/runners) (state flips between `Idle` and `Offline`).

## Full uninstall

When you want the runner gone for good (the GitHub-hosted minute quota came back, or you're rebuilding the Pi):

```bash
cd ansible
mise exec -- ansible-playbook -i inventory/production.yml \
    playbooks/deploy-github-runner.yml \
    --tags github_runner,uninstall \
    --extra-vars github_runner_uninstall=true \
    --diff
```

This stops the service, calls `config.sh remove` so the runner disappears from the GitHub UI, deletes the systemd unit + drop-in + install dir + `github-runner` user + group. `libicu-dev` and `mise` stay on the host (used elsewhere). Idempotent — a second run is a no-op.

After uninstall, **also revert the `runs-on: [self-hosted, arm64, pi-homelab]` lines in `.github/workflows/ci-validation.yml` back to `runs-on: ubuntu-latest`** — otherwise the affected jobs queue indefinitely.

## Why not actions-runner-controller (ARC) in k8s?

Considered and rejected for this iteration: ARC requires cert-manager + a webhook + RunnerSet CRDs + a Helm chart pin. systemd on Pi-4 is one role + one secret + zero new dependencies. If the runner fleet grows to >3 instances or ephemeral-per-job becomes a requirement, revisit ARC.

## Testing

Run Molecule tests locally:
```bash
make test-molecule-github_runner
```

See [`docs/operations/testing.md`](../../../docs/operations/testing.md) for the full testing guide and [`docs/contributing/role-template.md`](../../../docs/contributing/role-template.md) for the new-role checklist.
