#!/usr/bin/env python3
"""Post-deploy observability gate — fails the deploy if Prometheus reports
trouble in the configured observation window.

ArgoCD reporting "Synced + Healthy" is necessary but not sufficient: a pod
can flap into CrashLoopBackOff seconds after the sync completes, or a
deployment can satisfy `availableReplicas` while a sidecar is OOMing. This
gate runs AFTER `make validate-argocd-synced` and queries Prometheus
directly for the signals that catch those silent failures:

  - kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}
  - kube_deployment_status_replicas_unavailable
  - kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}

Exit 0 if all queries return 0 over the window, 1 otherwise. Designed for
CI: the caller is responsible for kubectl port-forwarding Prometheus to
localhost (or setting PROMETHEUS_URL).

Usage:
  python3 bin/post_deploy_observability_gate.py
  PROMETHEUS_URL=http://localhost:9090 OBSERVATION_WINDOW=300 \\
    python3 bin/post_deploy_observability_gate.py

Env:
  PROMETHEUS_URL       Default http://localhost:9090
  OBSERVATION_WINDOW   PromQL [Ns] window. Default 300 (5min).
  REQUEST_TIMEOUT      HTTP timeout per query (s). Default 15.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import NamedTuple


class Check(NamedTuple):
    name: str
    promql: str
    severity: str  # 'fail' or 'warn'


def build_checks(window: int) -> list[Check]:
    w = f"[{window}s]"
    return [
        Check(
            name="OOMKilled containers",
            promql=f'sum(increase(kube_pod_container_status_last_terminated_reason{{reason="OOMKilled"}}{w})) or vector(0)',
            severity="fail",
        ),
        Check(
            name="Deployments with unavailable replicas",
            promql="sum(kube_deployment_status_replicas_unavailable) or vector(0)",
            severity="fail",
        ),
        Check(
            name="Containers in CrashLoopBackOff",
            promql='sum(kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}) or vector(0)',
            severity="fail",
        ),
        Check(
            name="Pods stuck Pending",
            promql='sum(kube_pod_status_phase{phase="Pending"}) or vector(0)',
            severity="warn",
        ),
    ]


def query_prometheus(base_url: str, promql: str, timeout: float) -> float:
    """Run an instant PromQL query, return scalar result. Raises on HTTP / parse error."""
    url = f"{base_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    with urllib.request.urlopen(
        url, timeout=timeout
    ) as resp:  # noqa: S310 — internal URL
        payload = json.loads(resp.read())
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    result = payload["data"]["result"]
    # `or vector(0)` ensures we always get one sample.
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def evaluate(
    base_url: str, checks: list[Check], timeout: float
) -> tuple[int, list[dict]]:
    """Run all checks. Return (exit_code, summaries).

    exit_code is 1 if any 'fail'-severity check is non-zero; warn-severity
    checks log loudly but don't fail the build.
    """
    summaries: list[dict] = []
    failed = False
    for c in checks:
        try:
            value = query_prometheus(base_url, c.promql, timeout)
        except Exception as e:  # noqa: BLE001 — we want to surface the error message
            summaries.append(
                {"name": c.name, "value": None, "error": str(e), "severity": c.severity}
            )
            failed = True
            print(f"  ❌ {c.name}: query error — {e}")
            continue

        ok = value == 0
        marker = "✅" if ok else ("❌" if c.severity == "fail" else "⚠️ ")
        print(f"  {marker} {c.name}: {value:g}")
        summaries.append(
            {"name": c.name, "value": value, "severity": c.severity, "ok": ok}
        )
        if not ok and c.severity == "fail":
            failed = True

    return (1 if failed else 0), summaries


def main(argv: list[str] | None = None) -> int:
    base_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    window = int(os.environ.get("OBSERVATION_WINDOW", "300"))
    timeout = float(os.environ.get("REQUEST_TIMEOUT", "15"))

    print(f"🔭 Post-deploy observability gate against {base_url} (window={window}s)")
    checks = build_checks(window)
    code, _ = evaluate(base_url, checks, timeout)
    if code != 0:
        print(
            "\n❌ Observability gate FAILED — see checks above. Triggering rollback path."
        )
    else:
        print("\n✅ Observability gate passed — cluster is quiet over the window.")
    return code


if __name__ == "__main__":
    sys.exit(main())
