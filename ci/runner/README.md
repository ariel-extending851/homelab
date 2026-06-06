# Docker-based GitHub Actions self-hosted runner

Long-lived runner that uses the host's Docker daemon for sibling containers. Targets pc-tower (Fedora Bluefin, 12c/15G, x86_64) running on `192.168.8.120`.

## Why Docker (vs. systemd)

| | Docker compose (this dir) | Ansible/systemd (`ansible/roles/github_runner/`) |
|---|---|---|
| Host requirement | docker daemon + socket access | systemd + SSH for ansible reach |
| Persistence | container managed by host Docker (survives DevPod exits) | systemd unit (host reboot) |
| Sibling containers | yes (k3d/kind/Trivy spawn on host daemon) | yes if Docker is also installed |
| Resource caps | compose `deploy.resources` | systemd drop-in |
| Bootstrap inside a DevContainer | works (this) | needs sshd on host |

If you're on a Pi (no Docker) or want the runner managed by systemd, use the Ansible role instead.

## Bootstrap

```bash
# From repo root
make runner-up
```

`make runner-up` decrypts `ansible/group_vars/github_runners.sops.yml` to extract the PAT, exports `ACCESS_TOKEN`, then runs `docker compose up -d`. The runner registers as `pc-tower-runner` with labels `self-hosted, x64, pc-homelab`.

Verify: <https://github.com/ariel-extending851/homelab/settings/actions/runners> should show `pc-tower-runner` as `Idle` within ~30 s.

## Operations

```bash
# Tail logs (registration + jobs)
make runner-logs

# Pause for interactive work (gaming, video calls)
make runner-down
# Resume later
make runner-up

# Recreate from scratch (wipes the work cache too)
make runner-reset
```

## Coexistence with the host

Resource caps in `docker-compose.yml`:

- `cpus: '6.0'` — half of 12 cores; foreground work always has 6 cores guaranteed.
- `memory: 8G` — leaves 7 GB for desktop + DevContainer + browser.
- No swap limit, no nice value (Docker doesn't expose them cleanly).

For tighter caps during a movie night or game, `make runner-down` is the simplest path — restart instantly afterward.

## Secrets

The PAT lives in `ansible/group_vars/github_runners.sops.yml` (encrypted with the repo's age key). `make runner-up` is the only place that decrypts it; no plaintext touches disk. Rotate the PAT by editing the SOPS file (`sops ansible/group_vars/github_runners.sops.yml`) and re-running `make runner-up`.

## Image pin

`myoung34/github-runner:2.319.1` matches the actions/runner version recorded in `ansible/roles/github_runner/defaults/main.yml`. The image bundles an `entrypoint.sh` that handles registration + de-registration. Bump in lockstep with the Ansible role's `github_runner_version` if you're rotating runner versions across both deployment modes.

## Decommission

```bash
make runner-down                 # stop + remove container
docker volume rm hl-github-runner-work   # also clear cached tools
# then revert the 5 `runs-on: [self-hosted, pc-homelab]` lines in
# .github/workflows/ci-validation.yml back to `runs-on: ubuntu-latest`.
```
