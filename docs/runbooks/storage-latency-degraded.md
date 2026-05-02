# Runbook: storage-latency degraded / monitor stalled

## Context

The `storage-latency` CronJob runs `fio` against `/var/lib/storage-latency` on `rasp-pi-04` every 6h, measuring p99 random read/write latency on the SD/USB media that backs `local-path` PVCs (Loki, Grafana, Prometheus, AdGuard, etc.). It exits with code:

- `0` — measured p99 within the 50ms SLA
- `1` — SLA breach (media is wearing out — degradation is the most common cause)
- `2` — exec failure (image pull, fio install, parser error)

Both `1` and `2` surface as a Failed Job, which fires `StorageLatencyDegraded`.

## Triage — distinguishing breach from exec failure

```bash
# Most recent Job's exit reason:
kubectl -n storage-latency get jobs -o json \
  | jq '.items | sort_by(.status.completionTime) | last | .status'

# Pod logs for the latest run (last 200 lines):
kubectl -n storage-latency logs -l app.kubernetes.io/name=storage-latency --tail=200

# Loki trend (Grafana → Explore):
{namespace="storage-latency"} | json | event="storage_latency"
```

Look for the last `event=storage_latency` line. It carries `p99_write_ms`, `p99_read_ms`, and `breach=true|false`. If you see no such line, it's an exec failure (rc=2).

## SLA breach (rc=1) — likely SD/USB wear

Symptoms:
- p99_write_ms or p99_read_ms > 50
- Often paired with reduced `write_iops` / `write_bw_kbs`

Action:
1. Confirm the trend in Loki — a one-off spike is noise, sustained breach across 3+ runs is real wear.
2. Plan a media swap. The RPi4 boots from USB; the swap procedure is in `docs/runbooks/control-plane-recovery.md` (boot from a fresh USB, restore from Velero).
3. While planning, drain non-critical workloads off `rasp-pi-04` to reduce wear pressure.

## Exec failure (rc=2) — test infrastructure

Symptoms:
- No `event=storage_latency` log lines in the latest run
- Pod logs show apt-get errors, fio not found, or parser tracebacks

Action:
1. Re-trigger manually: `kubectl -n storage-latency create job --from=cronjob/storage-latency manual-$(date +%s)`
2. If apt-get failed: check egress from `rasp-pi-04` (Tailscale, DNS).
3. If parser errored: compare `k8s/apps/storage-latency/configmap.yaml` against `bin/parse_fio_output.py` — they must stay in sync. The CRD copy is intentional duplication; if you've recently changed the source, re-render the ConfigMap.

## StorageLatencyMonitorStalled (no result in 24h)

Symptoms:
- Alert fires but no recent Failed Job

Action:
1. `kubectl -n storage-latency describe cronjob storage-latency` — look for "Cannot determine if job needs to be started" or scheduling errors.
2. Check that `rasp-pi-04` is `Ready`: `kubectl get nodes`.
3. Check the nodeSelector still matches: the CronJob pins `kubernetes.io/hostname: rasp-pi-04`. Confirm with `kubectl get nodes --show-labels`.

## SLA tuning

If the 50ms threshold is wrong for the media in use, override per-CronJob via the env var:

```yaml
env:
  - name: THRESHOLD_MS
    value: "75"  # raise if normal-class SD card hits 50ms in steady state
```

Don't tune to silence the alert without doing the trend analysis first.
