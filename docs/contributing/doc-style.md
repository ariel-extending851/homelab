# Documentation Style Guide

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Templates and rules for writing documentation in this repo. Naming/versioning rules live in [`CONVENTIONS.md`](../CONVENTIONS.md); this file covers document-level style.

---

## Universal Header

Every doc starts with:

```markdown
# <Title>

> **Status:** Active | Draft | Deprecated
> **Last reviewed:** YYYY-MM-DD
> **Owner:** @ariel-extending851

<one-sentence purpose statement>

---
```

`Last reviewed` is the date you last verified the facts in the document, not the date you last edited it. Bump it during accuracy audits.

---

## Runbook Template

Runbooks (`docs/runbooks/`) are reactive on-call references. They use a severity table at the top:

```markdown
# Runbook: <symptom-described title>

| Field | Value |
|:--- |:--- |
| **Severity** | 🔴 Critical / 🟡 Warning / 🟢 Info |
| **Status** | ✅ Reviewed / ⏳ Draft |
| **Last Tested** | YYYY-MM-DD |
| **Owner** | @ariel-extending851 |

## Symptoms
What the operator sees / how the issue presents.

## Root Cause
Why this happens.

## Resolution
Numbered steps; commands in fenced blocks.

## Verification
How to confirm the fix worked.

## Prevention
Optional: monitoring, automation, or process changes.
```

---

## Service Template

Service docs (`docs/services/<app>.md`) describe one deployed application:

```markdown
# <App Name>

> **Status:** Active · **Node:** rasp-pi-04 · **Namespace:** media · **Ingress:** https://<app>.tail57bf10.ts.net
> **Manifests:** [`k8s/apps/<app>/`](../../k8s/apps/<app>/) · **Last reviewed:** YYYY-MM-DD

## Overview
What it is, why we run it.

## Architecture
Components, sidecars, persistence, network policies.

## Configuration
Key knobs, secrets pattern, environment variables.

## Operations
Common admin tasks (restart, backup, upgrade).

## Troubleshooting
Top 3-5 known issues with fixes.
```

---

## In-Tree Stub Template

Where docs are co-located with code (e.g., `k8s/apps/adguard/README.md`, `infra/aws/README.md`), keep a thin stub that points at the canonical doc:

```markdown
# <Component>

<one-line purpose statement>

For full documentation see **[docs/services/<name>.md](../../../docs/services/<name>.md)**.

| File | Purpose |
|---|---|
| `deployment.yaml` | … |
| `service.yaml` | … |
```

---

## Markdown Mechanics

- **Headings:** ATX (`#`); one H1 per file; don't skip levels
- **Code blocks:** triple backticks with a language hint
- **Links:** relative paths for internal references; absolute `https://` for external
- **Tables:** keep narrow enough to read on a phone
- **Diagrams:** prefer Mermaid (`\`\`\`mermaid`) over external image hosts
- **Emoji:** use sparingly in headings as visual anchors (🚀 🏗️ 📖); never inside paragraphs
