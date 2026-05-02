# Image Upgrade Sprint — 2026 Q3

> **Owner:** @ariel-extending851
> **Target completion:** 2026-07-30 (matches `.trivy-image-allowlist.txt` review-by date)
> **Status:** Phase 1 manifest changes done (2026-05-02); awaiting deploy + soak

## Phase 1 outcome — Go-stdlib pattern (read before starting future phases)

When Phase 1 ran (2026-05-02), 4 of 5 bumped images **still tripped Trivy strict** despite jumping to the latest upstream stable tag. Every remaining HIGH/CRITICAL was a **Go stdlib or Go library CVE** (`stdlib`, `google.golang.org/grpc`, `go.opentelemetry.io/otel/sdk`, `opencontainers/selinux`) baked into the upstream's static binary. We can't fix these without an upstream rebuild against a newer Go toolchain.

**Implication for the remaining phases:** when bumping Prometheus / OTel / Loki / Grafana / Velero, expect the same pattern — getting to **zero CVEs** is not always possible at PR time. Acceptance criteria for those phases is **CVE count meaningfully reduced** plus all functional tests green, NOT necessarily a clean trivy-strict exit. Where residual CVEs persist, re-allowlist with a 90-day review-by and document that we're waiting on upstream rebuild.

Concrete numbers, Phase 1 (HIGH+CRITICAL fixable counts):

| Image | Before | After | Δ |
|---|---|---|---|
| AdGuard | 11 | **0** (clean ✅) | -11 |
| Blackbox | 22 | 8 | -14 |
| Node-exporter | 17 | 11 | -6 |
| kube-state-metrics | 20 | 10 | -10 |
| Golink | (re-pinned) | 4 | n/a |

## Why

10 of 13 deployed images carry HIGH/CRITICAL CVEs that are currently allowlisted in [`.trivy-image-allowlist.txt`](../../.trivy-image-allowlist.txt). The allowlist is **suppression, not mitigation** — every entry expires 2026-07-30. This runbook sequences the upgrades from lowest to highest blast radius so we land them with the most rollback room.

## Strategy: do nothing brave

- **One PR per phase** (Phase 1 batches patch bumps; Phases 2-6 are single-app).
- **Each PR removes its entries from the allowlist** as part of the change — Trivy strict gate proves the bump worked.
- **Velero backup before each phase** — non-negotiable; the file ID becomes the rollback restore point.
- **Soak time between phases** — bugs surface under real traffic. Don't compress.
- **Stop on first failure** — investigate before queueing the next phase.

## Pre-flight checklist (run before EVERY phase)

```bash
# 1. Local validation gate
make test-offline-required          # all ~13 offline suites must pass

# 2. Cluster baseline
kubectl get apps -n argocd          # all Synced + Healthy
make smoke-test                     # 20+ checks across cluster

# 3. Backup gate
velero backup create pre-upgrade-$(date +%Y%m%d-%H%M) \
  --include-namespaces grafana,loki,prometheus,otel-collector,velero,adguard,golink,kube-state-metrics,node-exporter,blackbox \
  --wait
velero backup describe <backup-name>   # confirm Phase=Completed, no errors

# 4. Metrics baseline (informational — saves grief during regression hunt)
# Snapshot the Grafana "Homelab K3s Overview" dashboard panel-by-panel
# Save as PNG attached to the PR description
```

## Phases

Ordered by risk, lowest → highest. Soak before promoting to next phase.

### Phase 1 — Patch-level batch (1 PR, ≈30 min effort) — manifest changes done 2026-05-02

Five patch/minor bumps with no documented breaking changes. Group into a single PR for shared backup window.

| App | Current | Target | Outcome | File |
|---|---|---|---|---|
| AdGuard Home | `v0.107.71` | `v0.107.74` | clean ✅ | `k8s/apps/adguard/deployment.yaml` |
| Blackbox Exporter | `v0.24.0` | `v0.28.0` | -14 CVEs, allowlisted | `k8s/apps/blackbox/deployment.yaml` |
| Node Exporter | `v1.7.0` | `v1.9.1` | -6 CVEs, allowlisted | `k8s/apps/node-exporter/daemonset.yaml` |
| kube-state-metrics | `v2.9.2` | `v2.18.0` | -10 CVEs, allowlisted | `k8s/apps/kube-state-metrics/deployment.yaml` |
| Golink | `main@sha256:ba53…` | `main@sha256:011e6a…` | re-pinned to current `:main` | `k8s/apps/golink/deployment.yaml` |

**Verification:**
```bash
make test-trivy-strict              # confirm bumped images pass without allowlist
make test-k8s-policies-critical     # OPA still green
kustomize build k8s/apps > /dev/null # renders cleanly
# Push PR; after merge + ArgoCD sync:
make smoke-test
make test-e2e-post-deploy
```

**Rollback:** `git revert <sha>` → ArgoCD reverts. PVCs untouched.
**Soak:** 24h before Phase 2.

### Phase 2 — Velero v1.15+ (1 PR)

Standalone; no in-cluster consumers. Velero CRDs are backwards-compatible per upstream changelog; existing schedules + backups remain valid.

**Files:** `k8s/apps/velero/deployment.yaml`, `k8s/apps/velero/daemonset.yaml`

**Pre-checks specific to this phase:**
- Read [Velero v1.15 release notes](https://github.com/vmware-tanzu/velero/releases) — call out any deprecated flags in our `args:` list
- Confirm CSI snapshot driver compat (we use restic uploader — `--uploader-type=restic` still supported in v1.15+)

**Verification:**
```bash
make test-dr                        # Molecule scenario re-runs the role logic
# Post-deploy:
velero backup create test-post-upgrade --wait
velero backup describe test-post-upgrade   # Phase=Completed
velero restore create --from-backup test-post-upgrade --dry-run  # validate
```

**Rollback:** revert PR; if backup CRD schema diverged, restore from `pre-upgrade-*` Velero backup of `velero` namespace.
**Soak:** 48h. Wait for at least one scheduled backup cycle.

### Phase 3 — Prometheus 2.55+ (1 PR)

Minor version. TSDB format is stable across 2.45 → 2.55 (verified per upstream).

**File:** `k8s/apps/prometheus/deployment.yaml`

**Pre-checks:**
- Read [Prometheus 2.46-2.55 changelogs](https://github.com/prometheus/prometheus/blob/main/CHANGELOG.md) — flag any flag deprecations (e.g., `--storage.tsdb.retention` was already replaced by `.time` in 2.30+, but double-check)
- Snapshot TSDB before bump:
  ```bash
  kubectl exec -n prometheus deploy/prometheus -- \
    promtool tsdb create-blocks-from snapshot /prometheus
  ```
- Velero backup of `prometheus` namespace (already in pre-flight)

**Verification:**
```bash
# After ArgoCD sync:
curl -s http://prometheus.lan:9090/-/ready              # 200
curl -s http://prometheus.lan:9090/api/v1/targets | jq '.data.activeTargets | length'  # baseline
curl -s http://prometheus.lan:9090/api/v1/rules | jq '.data.groups | length'           # rules loaded
# Sanity query
curl -sG http://prometheus.lan:9090/api/v1/query \
  --data-urlencode 'query=sum(up)'
```

**Rollback:** revert PR. PVC contents stay valid (TSDB is forward+backward compatible across minor versions).
**Soak:** 48h. Watch for scrape errors, alert evaluation lag.

### Phase 4 — OTel Collector 0.115+ (1 PR)

⚠️ **Config breaking changes** between 0.102 and 0.115. Plan carefully.

**File:** `k8s/apps/otel-collector/daemonset.yaml` + `configmap.yaml`

**Pre-checks (mandatory):**
- Read [OTel Collector breaking-changes log](https://github.com/open-telemetry/opentelemetry-collector/blob/main/CHANGELOG.md) for every release between 0.102 and target
- Common breaks: `service::pipelines::*::processors` ordering rules, `loki` exporter renamed to `lokiexporter`, hostmetrics scraper config keys
- Validate new config locally **before** the PR:
  ```bash
  docker run --rm -v $PWD/k8s/apps/otel-collector/configmap.yaml:/etc/otel/config.yaml \
    otel/opentelemetry-collector-contrib:0.115.0 \
    --config=/etc/otel/config.yaml --dry-run
  ```

**Verification:**
```bash
# After ArgoCD sync:
kubectl logs -n otel-collector ds/otel-collector --tail=50  # no schema errors
# Confirm log shipping
logcli query --limit 1 '{namespace="otel-collector"}'
# Confirm metrics are flowing
curl -sG http://prometheus.lan:9090/api/v1/query \
  --data-urlencode 'query=otelcol_exporter_sent_logs_records'
```

**Rollback:** revert PR. otel-collector is stateless — no data loss on rollback.
**Soak:** 24h. Watch for receiver/exporter accepted/refused metrics.

### Phase 5 — Loki 3.x (1 PR)

⚠️ **Schema migration.** This is the riskiest of the chain.

**Files:** `k8s/apps/loki/deployment.yaml`, `k8s/apps/loki/configmap.yaml`

**Migration approach:** add new schema starting from a future date; keep old schema accessible for historical queries. From [Loki upgrade docs](https://grafana.com/docs/loki/latest/setup/upgrade/), the v12 → v13 schema change is forward-compatible — Loki reads old blocks via the legacy schema entry and writes new blocks under the new schema.

**Pre-checks (mandatory):**
- Velero backup of `loki` namespace + PVC (covered in pre-flight)
- Add new schema entry in `loki.yaml` config **before** bumping image:
  ```yaml
  schema_config:
    configs:
      - from: 2022-01-01           # existing
        store: boltdb-shipper
        object_store: filesystem
        schema: v12
        index: { prefix: index_, period: 24h }
      - from: 2026-07-01           # new — date must be in the future at PR open
        store: tsdb
        object_store: filesystem
        schema: v13
        index: { prefix: index_v13_, period: 24h }
  ```
- Push the schema-only change first; let it soak 24h; **then** bump the image in a follow-up PR

**Verification:**
```bash
# After ArgoCD sync (image bump):
kubectl logs -n loki deploy/loki --tail=100 | grep -E "schema|panic|fatal"  # nothing fatal
# Old logs still queryable
logcli query --limit 5 '{namespace="grafana"}' --from=$(date -d '7 days ago' --iso-8601=s)
# New logs ingesting
logcli query --limit 5 '{namespace="grafana"}' --since=5m
```

**Rollback:** revert image bump PR (config can stay — it's additive). If chunks corrupted, restore PVC from Velero.
**Soak:** 72h — logs accumulate; verify query patterns over multi-day windows.

### Phase 6 — Grafana 11 LTS (1 PR)

⚠️ **Dashboard regression risk.** Highest user-visible blast radius.

**File:** `k8s/apps/grafana/deployment.yaml`

**Pre-checks (mandatory):**
- Read [Grafana 11 LTS migration guide](https://grafana.com/docs/grafana/latest/upgrade-guide/upgrade-v11.0/) end-to-end
- Common breaks: Angular plugins removed (check installed plugins), `transformations` API changes, `query.refId` mandatory, alerting v1 → v2 if not already migrated
- Export every dashboard JSON via API as a backup:
  ```bash
  kubectl exec -n grafana deploy/grafana -- \
    grafana-cli admin export-dashboard > /tmp/dashboards-pre-upgrade.json
  # OR via API per-folder
  ```
- If feasible: spin up a separate Grafana 11 pod against the same data sources in a dev namespace; load dashboards; verify panels render

**Verification:**
```bash
# After ArgoCD sync:
kubectl logs -n grafana deploy/grafana --tail=100 | grep -iE "error|panic|migration"
# Health check
curl -s http://grafana.lan:3000/api/health
# Data source health (per source)
curl -s -H "Authorization: Bearer $TOKEN" http://grafana.lan:3000/api/datasources | \
  jq -r '.[] | "\(.name) \(.type)"' | while read name type; do
    echo "Testing $name..."
    # Manually load each dashboard in the UI; can't fully automate panel render
  done
```

**Manual gate:** open every dashboard in the UI; confirm panels populate and time range works. Cannot be automated reliably.

**Rollback:** revert PR. PVC contents stay (Grafana 10 reads its own DB schema; 11 may upgrade DB schema irreversibly — the **Velero backup is the recovery path**).
**Soak:** 1 week before declaring done.

## Universal rollback playbook

```bash
# 1. Revert
git revert <commit-sha>
git push

# 2. ArgoCD auto-syncs to the previous spec
argocd app sync <app>          # force if auto-sync disabled
argocd app wait <app> --sync --health

# 3. If data layer corrupted (PVC contents):
velero restore create --from-backup pre-upgrade-<TS> \
  --include-resources persistentvolumeclaims,persistentvolumes \
  --include-namespaces <ns>

# 4. Validate recovery
make smoke-test
make test-e2e-post-deploy
```

## Sign-off criteria (per phase)

- [ ] All smoke + e2e tests pass after deploy
- [ ] `make test-trivy-strict` passes (image is no longer allowlisted)
- [ ] No new alerts firing in Prometheus that aren't pre-existing
- [ ] Critical dashboards verified manually (Grafana phase only)
- [ ] Soak window completed without incidents
- [ ] Allowlist entry removed from `.trivy-image-allowlist.txt` in same PR

## Tracking

PR title format: `chore(upgrade): <app> <oldVer>→<newVer>`

PR description should include:
- Pre-upgrade Velero backup name + timestamp
- Verification command output (paste from runbook above)
- Soak start/end timestamps
- Any deviations from the runbook (be honest — future-you will thank past-you)

## Related

- [`.trivy-image-allowlist.txt`](../../.trivy-image-allowlist.txt) — current suppressions
- [`trivy-exceptions.md`](trivy-exceptions.md) — process for managing the allowlist
- [`observability-availability.md`](observability-availability.md) — what's at stake when Grafana/Loki/Prom downtime hits
- [`docs/security/fixes-backlog.md`](../security/fixes-backlog.md) — broader open security work
