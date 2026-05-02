"""Parse fio JSON output → Loki-friendly log line + SLA gate.

Companion to k8s/apps/storage-latency/cronjob.yaml. The CronJob runs fio
on the RPi4's local-path storage every 6h, pipes the result through this
parser, and exits with the parser's return code:

  0 → measured p99 within SLA, structured log line emitted
  1 → measured p99 breaches SLA threshold (Job fails → Prometheus alert
       fires via kube_job_status_failed{job_name=~"storage-latency-.*"})
  2 → fio data missing/unparseable (distinct from SLA breach so alerting
       can route execution problems differently from media degradation)

Schema of the structured log line (Loki-stable — do not break compat):
  {
    "event": "storage_latency",
    "host":  "<node hostname>",
    "threshold_ms": <float>,
    "breach": <bool>,
    "timestamp": "<ISO-8601 UTC>",
    "p99_write_ms": <float>,    # absent if fio gave no write percentile
    "p99_read_ms":  <float>,    # absent if no read percentile
    "write_iops":   <float>,
    "read_iops":    <float>,
    "write_bw_kbs": <int>,
    "read_bw_kbs":  <int>
  }
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Optional


def parse_fio_json(raw: str) -> dict:
    """Extract the metrics we care about from a fio job-result JSON document.

    Returns an empty dict on any kind of malformed input. The caller layers
    its own error handling on top — keeping this pure makes it trivially
    testable without subprocess plumbing.
    """
    if not (raw or "").strip():
        return {}
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    jobs = doc.get("jobs") or []
    if not jobs:
        return {}
    job = jobs[0]
    out: dict = {}

    for direction in ("write", "read"):
        section = job.get(direction) or {}
        if not section:
            continue
        clat = section.get("clat_ns") or {}
        # fio percentile keys are floats-as-strings: "99.000000"
        pct = clat.get("percentile") or {}
        p99_ns = pct.get("99.000000") or pct.get("99.0") or pct.get("99")
        if p99_ns is not None:
            out[f"p99_{direction}_ms"] = round(float(p99_ns) / 1_000_000, 3)
        if "iops" in section:
            out[f"{direction}_iops"] = float(section["iops"])
        if "bw" in section:
            out[f"{direction}_bw_kbs"] = int(section["bw"])
    return out


def breaches_threshold(metrics: dict, threshold_ms: float) -> bool:
    """True if any measured p99 exceeds the SLA threshold.

    Missing metrics are treated as "no breach" — fail-quiet, since a
    missing-data state should be alerted via rc=2 (exec failure), not a
    false-positive SLA breach.
    """
    for key in ("p99_write_ms", "p99_read_ms"):
        val = metrics.get(key)
        if val is None:
            continue
        if val > threshold_ms:
            return True
    return False


def render_log_line(metrics: dict, host: str, threshold_ms: float) -> str:
    """Serialize metrics + verdict as a single JSON line for Loki ingestion."""
    payload = {
        "event": "storage_latency",
        "host": host,
        "threshold_ms": threshold_ms,
        "breach": breaches_threshold(metrics, threshold_ms),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload.update(metrics)
    return json.dumps(payload, sort_keys=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="-",
        help="Path to fio JSON output (default: read stdin)",
    )
    parser.add_argument(
        "--threshold-ms",
        type=float,
        default=50.0,
        help="p99 latency SLA in milliseconds (default: 50.0)",
    )
    parser.add_argument(
        "--host",
        default="unknown",
        help="Node hostname tag for the log line (e.g. rasp-pi-04)",
    )
    args = parser.parse_args(argv)

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(args.input, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"failed to read {args.input}: {exc}", file=sys.stderr)
            return 2

    metrics = parse_fio_json(raw)
    if not metrics:
        # Distinct rc so alerting can route exec-failure separately.
        print(f"no parseable fio metrics in input ({len(raw)} bytes)", file=sys.stderr)
        return 2

    print(render_log_line(metrics, host=args.host, threshold_ms=args.threshold_ms))
    return 1 if breaches_threshold(metrics, args.threshold_ms) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
