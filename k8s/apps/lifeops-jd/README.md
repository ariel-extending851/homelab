# lifeops-jd

Quarkus CronJob that organizes Gmail into Johnny.Decimal labels via Claude
Haiku 4.5 and creates Calendar events / Tasks for actionable items detected.

**Application source**: <https://github.com/ariel-extending851/lifeops-jd> (private)
**Image**: `ghcr.io/ariel-extending851/lifeops-jd:<tag>` (private)
**Pattern reference**: mirrors `k8s/apps/jobhunter/` (dedicated Postgres + SOPS secrets).

> First sync after merge will **fail** until the OAuth + Anthropic secrets
> are replaced with real values. The CronJob will land in a `BackoffLimit`
> state but the rest of the namespace (Postgres, ConfigMap, NetworkPolicy)
> comes up cleanly. See "Before first deploy" below.

## Manifests in this directory

| File | Purpose |
|---|---|
| `namespace.yaml` | Pod Security `restricted` namespace `lifeops-jd` |
| `postgres.yaml` | Headless Service + StatefulSet (postgres:16-alpine, 2Gi PVC) |
| `cronjob.yaml` | Every-5-min tick, `concurrencyPolicy: Forbid`, JVM-profile resource limits |
| `configmap-taxonomy.yaml` | Johnny.Decimal taxonomy mounted at `/etc/lifeops/taxonomy` |
| `networkpolicy.yaml` | Default-deny + explicit egress to googleapis/anthropic + PG ingress |
| `secret-db.yaml` | SOPS — Postgres credentials |
| `secret-oauth.yaml` | SOPS — Google `credentials.json` + `token.json` (both required) |
| `secret-anthropic.yaml` | SOPS — Anthropic API key |
| `kustomization.yaml` | Kustomize root |
| `catalog-info.yaml` | Backstage component |

## Before first deploy

The PR ships the secrets with **placeholder values** so the SOPS pipeline is
exercised and ArgoCD can sync the rest of the namespace. Replace them
before the CronJob can actually run:

```bash
# 1. Generate the Google OAuth files locally (one-time consent flow):
#    See https://github.com/ariel-extending851/lifeops-jd/blob/main/docs/auth-setup.md
#    Result: credentials.json + token.json in ~/.config/lifeops-jd/

# 2. Edit each secret in-place (decrypt → edit → re-encrypt automatic):
sops k8s/apps/lifeops-jd/secret-db.yaml         # set a strong password
sops k8s/apps/lifeops-jd/secret-anthropic.yaml  # paste your sk-ant-* key
sops k8s/apps/lifeops-jd/secret-oauth.yaml      # paste credentials.json + token.json

# 3. Commit + push; ArgoCD picks up automatically.
```

## Verifying once deployed

```bash
# Force a tick (don't wait 5 min)
kubectl create job -n lifeops-jd manual-smoke --from=cronjob/lifeops-jd-tick
kubectl logs -n lifeops-jd job/manual-smoke -f
```

## Architecture, runbooks, OAuth setup

Lives in the source repo
([ariel-extending851/lifeops-jd](https://github.com/ariel-extending851/lifeops-jd)):

- `docs/architecture.md` — design + why Quarkus/Java over Python
- `docs/auth-setup.md` — GCP OAuth desktop client walkthrough
- `docs/deployment.md` — end-to-end deploy verification
- `docs/runbooks/token-refresh-failed.md` — recovery when Google `401`s
