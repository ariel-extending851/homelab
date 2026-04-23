# Archive

> **Status:** Active (the index; not the contents)
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel99gf

This directory holds documents that are no longer actively maintained but are kept for historical context. They are **excluded from CI link-checking** (`docs/archive/` is in the `link-checker.yml` exclusion list), so broken links here will not fail builds.

## What lives here

| Subdirectory | Contents |
|---|---|
| `incidents/` | Resolved post-mortems and incident reports |
| `status/` | Point-in-time status snapshots and session handoffs |
| `plans/` | Plans that were either completed or abandoned |
| `analysis/` | One-off analyses whose recommendations have been actioned |
| `test-results/` | Dated test-run snapshots |

## Policy

- **Do not edit archived files** — if a fact in them is still relevant, copy it into an active doc and cite the date.
- **Do not link to archived files from active docs** — the link-checker won't complain, but the content shouldn't be considered authoritative.
- **When archiving a new file**, prepend a one-line "Archived YYYY-MM-DD: <reason>" notice at the top.
- **Standalone files** (no subdirectory) are typically deprecated single docs — see `deprecated-architecture.md`, `deployment-summary.md`, `tailscale-sidecar-migration.md`.
