# Contributing to Homelab

Welcome! This guide helps you contribute to the homelab project, especially when adding new Ansible roles.

## Table of Contents

- [Adding a New Ansible Role](#adding-a-new-ansible-role)
- [Molecule Test Requirements](#molecule-test-requirements)
- [Development Workflow](#development-workflow)
- [Testing Guidelines](#testing-guidelines)

## Adding a New Ansible Role

Every Ansible role **MUST** have Molecule tests. This is enforced in CI/CD.

### Quick Start

**Option 1: Using the generator**
```bash
make new-role ROLE=my_new_role
```

**Option 2: Manual copy**
```bash
cp -r ansible/roles/.template ansible/roles/my_new_role
```

### Step-by-Step Setup

1. **Create role structure** (using one of the methods above)

2. **Replace placeholders**
   - Open `meta/main.yml` and replace `[ROLE_NAME]` with your role name
   - Open `README.md` and replace `[ROLE_NAME]` with your role name
   - Update `molecule/default/molecule.yml` host name: `[ROLE_NAME]-test`

3. **Define your role's variables**
   - Edit `defaults/main.yml`
   - Add all default variables with descriptions
   - Example: `my_config_value: "default"`

4. **Implement role tasks**
   - Edit `tasks/main.yml`
   - Add the actual role logic
   - Follow Ansible best practices

5. **Setup Molecule test for converge**
   - Edit `molecule/default/converge.yml`
   - Pre-create any directory stubs or mock binaries in `pre_tasks`
   - Apply your role via `roles:` section
   - Example:
     ```yaml
     - name: Converge — apply my_new_role
       hosts: all
       become: true
       gather_facts: true

       pre_tasks:
         # Create directories that role expects
         - name: Create /etc/myapp
           ansible.builtin.file:
             path: /etc/myapp
             state: directory
             mode: '0755'

       roles:
         - role: my_new_role
     ```

6. **Add verify assertions**
   - Edit `molecule/default/verify.yml`
   - Add at least ONE assertion that proves role executed successfully
   - Examples:
     ```yaml
     - name: Assert config file exists
       ansible.builtin.stat:
         path: /etc/myapp/config.yml
       register: config
       failed_when: not config.stat.exists

     - name: Assert service is configured
       ansible.builtin.command: systemctl is-enabled myapp
       changed_when: false
     ```

7. **Test locally**
   ```bash
   make test-molecule-my_new_role
   # or directly:
   cd ansible/roles/my_new_role && molecule test
   ```

8. **Validate structure**
   ```bash
   make validate-ansible-structure  # Checks all roles
   ```

## Molecule Test Requirements

### Minimum Files (Required)

Every role MUST have these files:

```
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

### Optional Files

- `prepare.yml` — Only if using `debian:bookworm-slim` base image
- Multiple scenarios (e.g., `install/`, `agent/`) — Only if role has distinct execution paths

### Molecule Configuration Decisions

#### Which Base Image?

**Option A: `debian:bookworm-slim`** (Recommended for simple roles)
- Pros: Minimal (~50MB), matches Raspberry Pi environment
- Cons: No python, no sudo, requires `prepare.yml` bootstrap
- Use when: Role doesn't need systemd or full Ubuntu environment
- Must include: `prepare.yml` with python3+sudo bootstrap
- Set in inventory: `ansible_become: false` (containers run as root)

**Option B: `geerlingguy/docker-ubuntu2204-ansible`** (Recommended for complex roles)
- Pros: Has python, sudo, systemd available (~500MB)
- Cons: Not minimal
- Use when: Role needs systemd or full Docker environment
- Can skip: `prepare.yml` (already has python/sudo)
- Set in inventory: `ansible_become: false` (containers run as root)

Both images are available; choose based on your role's needs.

#### Check Mode vs. Real Execution

**Check Mode** (dry-run testing)
```yaml
# molecule.yml
provisioner:
  name: ansible
  options:
    check: true  # ENTIRE converge runs in check mode
```
- Pros: Safe, deterministic, no actual changes
- Cons: Can't verify real tasks executed (only variable rendering)
- Use when: Role makes many external calls (curl, network access)

**Real Execution** (with stubs)
```yaml
# Don't set check: true in molecule.yml
# Instead, stub external commands in pre_tasks
```
- Pros: Tests actual task execution, can verify state changes
- Cons: Need to stub external binaries (curl, kubectl, systemctl)
- Use when: You want to verify files are created, templates rendered, etc.
- Most roles use this approach

#### Single vs. Multiple Scenarios

**Single scenario** (`default/`) — Suitable for:
- Simple roles (<100 lines)
- Roles with one execution path
- Example: `tailscale`, `argocd`

**Multiple scenarios** — Use if role has distinct paths:
- `default/` — Base case
- `agent/` — Alternative topology (k3s)
- `sops/` — Alternative config method (argocd)
- Example: `k3s` role with 4 scenarios

### Verify Assertions

At **minimum**, `verify.yml` must have at least **one assertion** that proves the role ran successfully:

```yaml
- name: Example 1: Assert file exists
  ansible.builtin.stat:
    path: /etc/myapp/config.yml
  register: config
  failed_when: not config.stat.exists

- name: Example 2: Assert permission
  ansible.builtin.stat:
    path: /usr/local/bin/myapp
  register: binary
  failed_when: binary.stat.mode != '0755'

- name: Example 3: Debug output (if no real files to check)
  ansible.builtin.debug:
    msg: "Role converged successfully"  # Better than nothing!
```

## Development Workflow

### 1. Create Branch
```bash
git checkout -b feat/add-my-role
```

### 2. Generate Role
```bash
make new-role ROLE=my_role
```

### 3. Implement Role
```bash
# Edit these files:
vim ansible/roles/my_role/defaults/main.yml
vim ansible/roles/my_role/tasks/main.yml
vim ansible/roles/my_role/meta/main.yml
vim ansible/roles/my_role/README.md
vim ansible/roles/my_role/molecule/default/molecule.yml
vim ansible/roles/my_role/molecule/default/converge.yml
vim ansible/roles/my_role/molecule/default/verify.yml
```

### 4. Test Locally
```bash
# Validate structure
make validate-ansible-structure

# Run full homologation suite
make test-homolog

# Or test just your role
make test-molecule-my_role
```

### 5. Commit & Push
```bash
git add ansible/roles/my_role/
git commit -m "feat(roles): Add my_role with Molecule tests"
git push origin feat/add-my-role
```

### 6. Open PR
- CI will automatically run `enforce-molecule-tests` job
- If any required molecule files are missing, CI will FAIL
- Fix any issues and force push

## Testing Guidelines

### Local Testing

```bash
# Test all roles
make test-molecule

# Test all structure
make validate-ansible-structure

# Test homologation suite (what CI runs)
make test-homolog

# Test one specific role
make test-molecule-my_role

# Or directly with molecule
cd ansible/roles/my_role
molecule test

# Debug a failing test
cd ansible/roles/my_role
molecule converge  # Stay connected to container
```

### CI Testing

When you push a PR:
1. `enforce-molecule-tests` runs first
   - Detects new roles
   - Validates molecule/ structure
   - FAILS if missing required files

2. `molecule` job runs
   - Runs ALL role tests
   - Must pass for merge

3. `pipeline-gate` checks all jobs passed

### Fixing CI Failures

**"Missing molecule/default/molecule.yml"**
- Solution: Copy `.template/molecule/default/molecule.yml` to your role

**"Missing converge.yml or verify.yml"**
- Solution: Copy template files and customize them

**"Molecule test failed — assertion failed"**
- Solution: Add more setup in `converge.yml` or fix assertion in `verify.yml`

**"ansible_become: false not set"**
- Solution: Add to `molecule.yml` inventory `group_vars.all`

## References

### Existing Roles to Study

- **Simple role**: `ansible/roles/tailscale/`
  - Single scenario, minimal tasks
  - Good starter pattern

- **Complex role**: `ansible/roles/k3s/`
  - Multiple scenarios (default, install, agent, health)
  - Multiple platform testing (Ubuntu, Amazon Linux)
  - Good reference for advanced patterns

### Role Template

- Template: `ansible/roles/.template/`
- Copy this to start any new role

### Molecule Documentation

- [Molecule Docs](https://molecule.readthedocs.io/)
- [Docker Driver](https://molecule.readthedocs.io/en/latest/configuration/)

### Testing Guide

- Full guide: `ansible/TESTING.md`
- Role-specific: `ansible/roles/.template/.template-checklist.md`

## Questions?

- Check `ansible/TESTING.md` for detailed testing guide
- Check `ansible/roles/.template/.template-checklist.md` for role creation steps
- Review existing roles for patterns and examples
