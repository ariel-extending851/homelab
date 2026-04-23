# Contributing Ansible Roles

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

How to scaffold, implement, and test a new Ansible role. Every role **must** ship with Molecule tests — the `enforce-molecule-tests` job in CI rejects roles missing `molecule/default/`.

For the broader contribution workflow (PR process, branches, code review) see the root [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

---

## Scaffold from Template

```bash
# Generator (preferred)
make new-role ROLE=my_new_role

# Or manual copy
cp -r ansible/roles/.template ansible/roles/my_new_role
```

Both create the same skeleton. The template lives at [`ansible/roles/.template/`](../../ansible/roles/.template/) and includes `defaults/`, `tasks/`, `meta/`, `molecule/default/{molecule.yml,converge.yml,verify.yml}`, `README.md`, and `prepare.yml` (used only with the slim base image).

Quick checklist for filling in the template: [`role-template.md`](role-template.md).

---

## Required Layout

```text
ansible/roles/my_role/
├── defaults/main.yml
├── tasks/main.yml
├── meta/main.yml
├── molecule/
│   └── default/
│       ├── molecule.yml        # REQUIRED
│       ├── converge.yml        # REQUIRED
│       └── verify.yml          # REQUIRED
└── README.md
```

Optional:

- `prepare.yml` — only with `debian:bookworm-slim` (bootstraps python + sudo)
- Multiple scenarios (`molecule/install/`, `molecule/agent/`, etc.) — only if the role has distinct execution paths (e.g., `k3s` has 4 scenarios for server/agent/install/health)

---

## Implement the Role

After scaffolding:

1. **Replace `[ROLE_NAME]` placeholders** in `meta/main.yml`, `README.md`, and `molecule/default/molecule.yml`.
2. **Variables** — declare every default in `defaults/main.yml` with a comment explaining what it does.
3. **Tasks** — implement in `tasks/main.yml`. Follow Ansible best practices: use modules over `command`, set explicit modes/owners on files, mark idempotency-friendly (avoid `changed_when: true` unless intentional).
4. **Meta** — fill `meta/main.yml` (galaxy_info, dependencies). Galaxy publishing isn't required, but the metadata is used by Molecule.

---

## Molecule Configuration Decisions

### Base image

| Choice | Pros | Cons | Use when |
|---|---|---|---|
| `debian:bookworm-slim` | ~50 MB; close to RPi env | No python/sudo by default — needs `prepare.yml` | Simple roles, no systemd needed |
| `geerlingguy/docker-ubuntu2204-ansible` | python + sudo + systemd built-in (~500 MB) | Larger | Complex roles, systemd services |

Set the base image in `molecule/default/molecule.yml` under `platforms[0].image`.

For containers, set `ansible_become: false` in the inventory (containers run as root by default — `become: true` causes weird sudo failures).

### Check mode vs. real execution

| Option | When |
|---|---|
| `provisioner.options.check: true` (full converge in check mode) | Role makes many external calls (curl, kubectl) — unsafe to run for real |
| Real execution + stub external binaries in `pre_tasks` | You want to verify state changes (file created, template rendered, etc.) — **most roles** |

### Single vs. multiple scenarios

- **`default/` only** — simple roles (<100 lines), one path. Examples: `tailscale`, `argocd`.
- **Multiple scenarios** — distinct execution modes. Example: `k3s` with `default/`, `install/`, `agent/`, `health/`.

---

## verify.yml — at least ONE assertion

CI rejects molecule scenarios with no real assertion. Examples:

```yaml
# Assert file exists
- name: Assert config file exists
  ansible.builtin.stat:
    path: /etc/myapp/config.yml
  register: cfg
  failed_when: not cfg.stat.exists

# Assert file mode
- name: Assert binary is executable
  ansible.builtin.stat:
    path: /usr/local/bin/myapp
  register: bin
  failed_when: bin.stat.mode != '0755'

# Assert service is enabled
- name: Assert service is enabled
  ansible.builtin.command: systemctl is-enabled myapp
  changed_when: false

# Last resort if you really have nothing concrete to check
- name: Confirm role converged
  ansible.builtin.debug:
    msg: "Role converged successfully"   # better than empty verify.yml
```

---

## Test Locally

```bash
# Validate structure (every role must have molecule/default/)
make validate-ansible-structure

# Run one role
make test-molecule-my_new_role

# Or directly
cd ansible/roles/my_new_role && molecule test

# Debug a failing test (stay connected to the container)
cd ansible/roles/my_new_role && molecule converge
molecule login   # exec into the container
```

The full Molecule test cycle: `dependency` → `cleanup` → `destroy` → `syntax` → `create` → `prepare` → `converge` → `idempotence` → `side_effect` → `verify` → `cleanup` → `destroy`.

---

## CI Behavior

When you push a PR:

1. **`enforce-molecule-tests` job** runs first — detects new roles, validates `molecule/default/` exists with all required files. **Fails** if missing.
2. **`molecule` job** runs — actually executes Molecule tests across roles. Must pass to merge.
3. **`molecule-arm64` job** — QEMU-based ARM64 matrix. Slower (~45 min) but catches Pi-only regressions.
4. **`pipeline-gate`** — checks all required jobs passed.

Common CI failures and fixes:

| Failure | Fix |
|---|---|
| `Missing molecule/default/molecule.yml` | Copy from `ansible/roles/.template/` |
| `Missing converge.yml or verify.yml` | Copy + customize from template |
| `Molecule test failed — assertion` | Add more `pre_tasks` setup in converge, or fix the assertion |
| `ansible_become: false not set` | Add to `molecule.yml` under `inventory.group_vars.all` |

---

## Reference Roles

When unsure how a pattern looks in practice:

| Role | Why study it |
|---|---|
| [`ansible/roles/tailscale/`](../../ansible/roles/tailscale/) | Simple, single-scenario, minimal task list — good starter pattern |
| [`ansible/roles/k3s/`](../../ansible/roles/k3s/) | Complex, 4 scenarios, multi-platform (Ubuntu + Amazon Linux) |
| [`ansible/roles/argocd/`](../../ansible/roles/argocd/) | Cluster-side install with state validation, demonstrates the SOPS sidecar pattern |
| [`ansible/roles/rpi_optimization/`](../../ansible/roles/rpi_optimization/) | Per-host system tuning, shows how to read `ansible_*` facts and act on them |

---

## Related

- **New-role template checklist:** [`role-template.md`](role-template.md)
- **Testing infrastructure:** [`../operations/testing.md`](../operations/testing.md)
- **Ansible operations (roles list, playbooks):** [`../operations/ansible.md`](../operations/ansible.md)
- **Molecule docs:** <https://ansible.readthedocs.io/projects/molecule/>
