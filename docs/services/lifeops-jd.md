# lifeops-jd

> **Status:** Experimental · **Node:** any · **Namespace:** lifeops-jd · **Ingress:** none (CronJob)
> **Manifests:** [`k8s/apps/lifeops-jd/`](../../k8s/apps/lifeops-jd/) · **Last reviewed:** 2026-06-04

Quarkus 3.20 CronJob that classifies Gmail into Johnny.Decimal labels via Claude Haiku 4.5 and creates Calendar events / Tasks for any actionable items detected.

Source code, OAuth walkthrough, and runbooks live in the dedicated repo:
<https://github.com/ariel-extending851/lifeops-jd> (private).

## Overview

- **Schedule:** every 5 min, `concurrencyPolicy: Forbid` (one tick at a time)
- **Image:** `ghcr.io/ariel-extending851/lifeops-jd` (private, JVM mode, ~170MB content)
- **State:** dedicated Postgres 16 StatefulSet (2 Gi PVC) — same pattern as `jobhunter`
- **LLM:** Claude Haiku 4.5 via `quarkus-langchain4j-anthropic` (prompt-caching of the taxonomy)
- **Auth:** OAuth 2.0 user-flow with refresh-token (not a Service Account — personal Gmail)

## Architecture

- **CronJob over Deployment** — no idle RAM on the Pi between ticks; crash recovery via concurrencyPolicy
- **`.NN` per (category, sender)** — stable across runs, persisted in `sender_decimal` table
- **Idempotency** — Gmail label `jd-processed` is the watermark; Postgres rows are a cache
- **JVM-profile resource limits** initially (request 256Mi, limit 512Mi); native ARM64 patch tracked as follow-up

## Why Java / Quarkus (override of the Python-default rule)

The user's general convention is Python-first; for this project Quarkus was an explicit choice to match the `jobhunter` pattern (which already runs Quarkus + Postgres on the same cluster). Don't "fix" back to Python — the consistency win matters.

## Setup: secrets

The PR that introduced this app shipped the three Secrets with **placeholder values** so the SOPS pipeline could be validated end-to-end. The CronJob will land in `BackoffLimit` until you replace them:

```bash
# 1. Get a Google OAuth desktop client + run the consent flow locally.
#    Full walkthrough: https://github.com/ariel-extending851/lifeops-jd/blob/main/docs/auth-setup.md

# 2. Edit each secret in-place (sops handles decrypt + re-encrypt):
sops k8s/apps/lifeops-jd/secret-db.yaml         # strong PG password
sops k8s/apps/lifeops-jd/secret-anthropic.yaml  # sk-ant-* key
sops k8s/apps/lifeops-jd/secret-oauth.yaml      # credentials.json + token.json

# 3. Commit + push. ArgoCD picks up automatically.
```

## Manifests in this directory

| File | Purpose |
|---|---|
| `namespace.yaml` | `lifeops-jd` at Pod Security `restricted` |
| `postgres.yaml` | Headless Service + StatefulSet (`postgres:16-alpine`) |
| `cronjob.yaml` | The tick; `*/5 * * * *`, JVM-profile resources |
| `configmap-taxonomy.yaml` | Johnny.Decimal taxonomy mounted at `/etc/lifeops/taxonomy` |
| `networkpolicy.yaml` | Default-deny + egress to googleapis + anthropic + PG |
| `secret-db.yaml` | SOPS — Postgres creds |
| `secret-oauth.yaml` | SOPS — `credentials.json` + `token.json` |
| `secret-anthropic.yaml` | SOPS — Anthropic API key |
| `catalog-info.yaml` | Backstage component |

## Verification

```bash
# Force a tick (don't wait for cron)
kubectl create job -n lifeops-jd manual-smoke --from=cronjob/lifeops-jd-tick
kubectl logs -n lifeops-jd job/manual-smoke -f
```

Successful tick produces JSON logs of the form:

```json
{"level":"INFO","message":"processed msg=18b... jd=31.03 conf=0.92"}
```

## Runbooks

- OAuth refresh failure: <https://github.com/ariel-extending851/lifeops-jd/blob/main/docs/runbooks/token-refresh-failed.md>
- Token revocation / re-consent: same doc, section "Re-issue the refresh token"
