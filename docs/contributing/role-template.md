# Role Template Checklist

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Quick checklist for filling in a new Ansible role scaffolded from the [Copier template at `templates/ansible-role/`](../../templates/ansible-role/). For the full contribution guide see [`ansible-roles.md`](ansible-roles.md).

---

## Quick Steps

1. **Scaffold the role** (Copier renders the template, so no placeholder substitution is needed):
   ```bash
   make new-role ROLE=my_new_role
   ```
   This calls `copier copy templates/ansible-role/ ansible/roles/my_new_role` under the hood. `copier` is installed via `mise install` (it's pinned in `.mise.toml`).

2. **Customize for your role:**
   - `defaults/main.yml` — declare all variables with defaults + comments
   - `tasks/main.yml` — implement the actual logic
   - `molecule/default/converge.yml` — add `pre_tasks` (stubs, directory creation, mock binaries)
   - `molecule/default/verify.yml` — at least ONE assertion that proves the role ran
   - `molecule/default/molecule.yml` — adjust base image / inventory if needed

3. **Test locally:**
   ```bash
   make test-molecule-my_new_role
   # or directly:
   cd ansible/roles/my_new_role && molecule test
   ```

4. **Reference patterns:**
   - **Simple role:** [`ansible/roles/tailscale/`](../../ansible/roles/tailscale/) — single scenario, basic
   - **Complex role:** [`ansible/roles/k3s/`](../../ansible/roles/k3s/) — 4 scenarios, multi-mode
   - **Cluster install:** [`ansible/roles/argocd/`](../../ansible/roles/argocd/) — for kubectl-using roles

---

## Always Required

- ✅ At least one task in `tasks/main.yml`
- ✅ At least one assertion in `verify.yml`
- ✅ Valid YAML across all files
- ✅ Metadata in `meta/main.yml`

---

## When Using `debian:bookworm-slim`

- ✅ Keep `prepare.yml` (it bootstraps python3 + sudo)
- ✅ Set `ansible_become: false` in `molecule.yml` inventory `group_vars.all`

## When Switching to `geerlingguy/docker-ubuntu2204-ansible`

- ✅ Remove or simplify `prepare.yml` (image already has python, sudo, systemd)
- ✅ Keep `ansible_become: false` (container still runs as root)

## Don'ts

- ❌ Don't mix bootstrap logic into `converge.yml` — that's what `prepare.yml` is for
- ❌ Don't use `become: true` with the slim image before sudo is installed
- ❌ Don't forget `ansible_become: false` in Docker containers (causes weird sudo failures)
- ❌ Don't commit a role without running `molecule test` at least once locally

---

## Testing Requirements (CI Enforces)

- `molecule/default/molecule.yml` exists
- `molecule/default/converge.yml` exists
- `molecule/default/verify.yml` exists
- At least one task in `verify.yml` (proves the role ran)

```bash
# Local validation
make validate-ansible-structure
make test-molecule-my_new_role
```

CI rejects new roles missing `molecule/default/` — there is no "I'll add tests later." escape hatch.

---

## Related

- **Full contribution guide:** [`ansible-roles.md`](ansible-roles.md)
- **Test infrastructure:** [`../operations/testing.md`](../operations/testing.md)
- **The Copier template:** [`templates/ansible-role/`](../../templates/ansible-role/)
