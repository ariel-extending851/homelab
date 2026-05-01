# Copier Templates

> **Status:** Active
> **Last reviewed:** 2026-05-01
> **Owner:** @ariel-extending851

Source-of-truth scaffolds for new project artifacts. Each subdirectory is a [Copier](https://copier.readthedocs.io/) template, invoked through a thin wrapper in `bin/` so muscle memory (`make new-role`, `make new-app`) keeps working.

---

## Templates

| Template | Wrapper | Make target | Output |
|---|---|---|---|
| [`ansible-role/`](ansible-role/) | [`bin/create_ansible_role.py`](../bin/create_ansible_role.py) | `make new-role ROLE=name` | `ansible/roles/<name>/` |
| [`k8s-app/`](k8s-app/) | [`bin/create_homelab_app.py`](../bin/create_homelab_app.py) | `make new-app APP=name` | `k8s/apps/<name>/` + auto-registers in `k8s/apps/kustomization.yaml` |

## Why Copier (and not Backstage)?

Hardware budget is the constraint: the cluster spans `t3.small`, `t3.medium`, RPi 4 (8 GB), and RPi 3 (1 GB). Backstage alone wants ~2 GB plus Postgres — not viable here. Copier delivers the parts that matter for a single-maintainer setup:

- **Interactive prompts** with validation (kebab-case, regex)
- **Conditional file generation** (`{% if needs_pvc %}pvc.yaml.jinja{% endif %}`)
- **Update path** — `copier update <dir>` propagates template changes into existing scaffolds
- **Compliance-as-code** — defaults encode `CONVENTIONS.md` (resource limits, doc headers, securityContext, kebab-case naming)

The complementary piece is [`bin/generate_service_catalog.py`](../bin/generate_service_catalog.py), which auto-fills the table in [`docs/services/README.md`](../docs/services/README.md) from `k8s/apps/<app>/` manifests — this covers Backstage's catalog use case without a runtime service.

## Working on a template

`copier` is pinned in [`.mise.toml`](../.mise.toml) — run `mise install` first. Then iterate locally:

```bash
# Render to a throwaway dir to inspect
copier copy --data role_name=demo --defaults templates/ansible-role/ /tmp/demo-role
# Or via the wrapper, which validates names and prints next steps:
make new-role ROLE=demo_role
```

Every `.jinja` file under `template/` compiles in CI via `make test-templates`. Conditional files use Jinja in their *path*, not their content (e.g. `{% if needs_ingress %}ingress.yaml.jinja{% endif %}`); update those when adding new optional resources.

## Conventions baked in

The k8s-app template enforces, by default, the rules from [`docs/CONVENTIONS.md`](../docs/CONVENTIONS.md):

- Kebab-case names with the `hl-` prefix asked but not forced (per §1.3 — app-specific resources in dedicated namespaces may omit the prefix)
- Doc header (`Status: Draft`, `Last reviewed: <today>`, `Owner: @ariel-extending851`) per §5
- Conservative `resources.requests`/`limits` aligned with [`docs/operations/resource-limits.md`](../docs/operations/resource-limits.md)
- `securityContext` with `runAsNonRoot: true` and capabilities `drop: ALL`
- Optional `nodeSelector` for `rpi3-only` / `rpi4-only` / `ec2-only` placement
