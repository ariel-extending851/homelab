# `homelab` CLI

> **Status:** Active · **Last reviewed:** 2026-05-01
> **Source:** [`bin/homelab.py`](../../bin/homelab.py)

Unified diagnostics CLI. Thin wrapper that re-exports logic already shipped in `bin/drift.py`, `bin/smoke_test.py`, `bin/preflight.py`, and `bin/morning_sync.py` so you can run common debugging tasks from one entry point during and after a deploy.

## Install (optional global symlink)

```bash
make install-cli   # symlinks bin/homelab.py → ~/.local/bin/homelab
homelab --help
```

If you'd rather not install globally, every command works through Make:

```bash
make homelab ARGS='argocd diagnose <app>'
make homelab ARGS='tf drift --summary'
```

## Subcommands

| Command | Purpose |
|---|---|
| `homelab argocd diagnose <app>` | Inspect an ArgoCD Application's sync, health, and conditions; surfaces the most recent error message in plain text |
| `homelab tf drift [--summary]` | Run the Terraform drift probe from `bin/drift.py` with the Argo + inventory checks skipped |

Run `homelab <subcommand> --help` for arguments (kubeconfig path, namespace, timeout). Defaults match the rest of the toolchain (`KUBECONFIG` env, `argocd` namespace).

## When to reach for it

| Situation | Command |
|---|---|
| ArgoCD UI shows an app `Degraded` and you're in a terminal | `homelab argocd diagnose <app>` |
| Suspect Terraform drift between `apply` and current AWS state | `homelab tf drift --summary` |
| Smoke-test failing post-deploy and you need a structured rerun | use `make smoke-test` (the source) |

## Related

- [`makefile-targets.md`](makefile-targets.md) — `make help` is the canonical Makefile reference
- [`../operations/testing.md`](../operations/testing.md) — full test profile catalog
- [`../runbooks/on-call.md`](../runbooks/on-call.md) — incident triage where this CLI is invoked
