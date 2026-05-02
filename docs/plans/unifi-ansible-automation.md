# UniFi Declarative Configuration via Ansible

> **Status:** Pending — start after PR #14 (`feat(unifi): on-demand UniFi controller`) merges
> **Owner:** @ariel-extending851
> **Created:** 2026-05-02

## Why

The on-demand UniFi controller (`k8s/apps/unifi/`) lets us adopt and configure
UniFi devices, but every config change still happens through the web UI. For a
fleet that grows beyond one Flex Mini, point-and-click drifts:

- Port profiles, VLANs, firewall rules end up undocumented.
- Reproducing a setup on a fresh controller (e.g. after a Velero restore that
  hits the "empty `/data/db`" gap noted in `k8s/apps/unifi/README.md`) means
  re-doing every click.
- Changes are not reviewable in PRs.

This plan wraps the controller's REST API in an Ansible role so that port
profiles and networks become declarative inputs in Git, applied via a wrapper
that handles `make unifi-up` → apply → `make unifi-down`.

## Scope

### In scope (MVP)

- Ansible role `ansible/roles/unifi_controller/` driving the controller via
  `ansible.builtin.uri` (no community module — the existing `unifi_*` modules
  on Galaxy are abandoned; the `gatekeeper` role's raw-HTTP pattern is the
  precedent here).
- Manage **port profiles** (PoE on/off, port VLAN access/trunk).
- Manage **per-device port overrides** (which port profile each port uses).
- Wrapper playbook `ansible/playbooks/network/configure_unifi.yml` that:
  1. Calls `make unifi-up` (delegate to localhost) and waits for `:8443/status`.
  2. Authenticates against `/api/login`, stores cookie.
  3. Reconciles port profiles + port overrides idempotently.
  4. Calls `make unifi-down`.
- New Makefile target `make unifi-apply` invoking the playbook.
- SOPS-encrypted `ansible/group_vars/all.sops.yaml` entry for
  `unifi_admin_user` / `unifi_admin_password` (reusing the existing
  `.sops.yaml` rule for `*Password`).

### Out of scope (later)

- Networks / VLAN definitions (POST `/api/s/<site>/rest/networkconf`).
- Firewall rules / groups.
- Firmware update orchestration (POST `/api/s/<site>/cmd/devmgr` with
  `"cmd": "upgrade"`).
- Site backup automation (`GET /api/s/<site>/cmd/backup`) committed to Git.
- Adoption automation (current manual flow in the README is fine for now).

## Prerequisites

1. **PR #14 merged** and ArgoCD synced — `kubectl -n unifi get deploy` shows
   both Deployments at `replicas: 0`.
2. **Admin bootstrapped manually once** via the web UI first-run wizard. The
   plan does **not** automate `POST /api/cmd/sitemgr/account-init` because
   that endpoint is fragile across controller versions. Operator records the
   chosen credentials and stores them via `sops -e` into the new group_vars
   entry.
3. **Switch already adopted** at least once (Flex Mini visible as
   `Connected` / `Provisioned` in the UI).

## Open decisions to confirm before coding

1. **Credentials path** — confirmed approach: operator-set admin via wizard,
   stored in SOPS `group_vars`. Alternative (auto-bootstrap via API) rejected
   as fragile.
2. **First-iteration scope** — confirmed: port profiles + port overrides only.
   Networks/VLANs in iteration 2.
3. **Test strategy** — Molecule with a disposable controller container, or
   skip Molecule for this role and rely on a `--check` smoke test against a
   live (ephemeral) controller? **Recommendation:** skip Molecule for v1
   (controller boot in container is slow and flaky); add `make unifi-apply
   CHECK=1` for dry-run instead.

## Implementation outline

### Files to create

| File | Purpose |
|---|---|
| `ansible/roles/unifi_controller/defaults/main.yml` | `unifi_controller_url`, `unifi_site` (default `default`), `unifi_port_profiles` (list of dicts), `unifi_device_port_overrides` (per-MAC list) |
| `ansible/roles/unifi_controller/vars/main.yml` | API path constants (`/api/login`, `/api/s/{{ site }}/rest/portconf`, `.../rest/user`) |
| `ansible/roles/unifi_controller/tasks/main.yml` | Orchestration: include auth → port_profiles → port_overrides |
| `ansible/roles/unifi_controller/tasks/auth.yml` | `uri:` POST `/api/login`, register cookie in fact |
| `ansible/roles/unifi_controller/tasks/port_profiles.yml` | GET existing → diff against desired → create/update/delete idempotently |
| `ansible/roles/unifi_controller/tasks/port_overrides.yml` | For each device, PUT the `port_overrides` array on the device document |
| `ansible/playbooks/network/configure_unifi.yml` | `pre_tasks: make unifi-up + wait_for`; `roles: unifi_controller`; `post_tasks: make unifi-down` (with `meta: end_play` if `KEEP_UP=1`) |
| `ansible/group_vars/all.sops.yaml` | `unifi_admin_user`, `unifi_admin_password` (encrypted via existing `.sops.yaml` regex `.*[Pp]assword`) |

### Files to modify

| File | Change |
|---|---|
| `Makefile` | Add `unifi-apply` target invoking `ansible-playbook -i ansible/inventory/production.yml ansible/playbooks/network/configure_unifi.yml`. Optional `CONFIG=path/to/profiles.yml` for `--extra-vars`. Add `unifi-apply` to `.PHONY`. |
| `ansible/inventory/group_vars/all.yml` (or similar) | Reference `unifi_controller_url: "https://{{ unifi_controller_node_ip }}:8443"` (resolved at runtime via `kubectl get pod -o jsonpath='{...hostIP}'`) |
| `docs/services/unifi.md` (new) | Operator runbook: how to edit port profiles, run `make unifi-apply`, troubleshoot |
| `k8s/apps/unifi/README.md` | Cross-link to this plan once role is live |

### API endpoints used

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/login` | Auth — returns cookie + CSRF token |
| GET | `/api/s/{{ site }}/rest/portconf` | List port profiles |
| POST | `/api/s/{{ site }}/rest/portconf` | Create port profile |
| PUT | `/api/s/{{ site }}/rest/portconf/{id}` | Update port profile |
| DELETE | `/api/s/{{ site }}/rest/portconf/{id}` | Delete port profile |
| GET | `/api/s/{{ site }}/stat/device` | List devices (find by MAC) |
| PUT | `/api/s/{{ site }}/rest/device/{id}` | Update `port_overrides` |
| POST | `/api/logout` | Clean session close |

## Verification

- [ ] `make unifi-apply` against a live controller creates a new port profile
      visible in the UI.
- [ ] Re-running `make unifi-apply` is idempotent (no changes reported).
- [ ] Editing a profile in the YAML and re-running pushes the diff (verify in
      UI).
- [ ] Removing a profile from YAML deletes it from the controller.
- [ ] Wrapper leaves the controller scaled to 0 after success.
- [ ] On failure mid-apply, controller is left scaled UP (so operator can
      inspect) — failure path documented.

## Risks

1. **Controller version drift** — REST paths change between major UniFi
   versions. Pinning `lscr.io/linuxserver/unifi-network-application:10.3.58`
   in `k8s/apps/unifi/deployment-unifi.yaml` mitigates this; bump image and
   role together.
2. **CSRF tokens** — newer controller versions require `X-Csrf-Token` from
   the login response on subsequent requests. Role must capture and replay.
3. **Race on adoption** — if a device is mid-provisioning when `port_overrides`
   PUT lands, the change is silently dropped. Add a `wait_for: status=Connected`
   gate before applying overrides.
4. **Credential exposure in logs** — every `uri:` task must set
   `no_log: true`. Add to a role-level default.

## Done criteria

- All MVP scope items shipped, documented, and exercised against the live
  controller at least once.
- Existing Flex Mini port config reproducible from `ansible/group_vars` after
  a wipe of `unifi-config-pvc` + re-adoption.
- Plan file moved to `docs/archive/plans/` with a one-line outcome note.
