"""RPi3 OOM resilience drill — fault-injection helpers + thin CLI.

Companion to `bin/tests/test_chaos_rpi3_oom.py`. The test imports the
helpers below; the CLI form (`python3 -m bin.chaos_rpi3_oom`) lets you
trigger a drill manually outside pytest, e.g. for ad-hoc debugging on
a development cluster.

Safety: this module *cannot* run against a node hosting AdGuard or UniFi
production pods. `assert_no_critical_workloads()` raises pytest.skip in
that case, and the CLI exits non-zero. CHAOS_ACK env gate is enforced
in the Makefile target — not here — so the helpers stay testable.

Discovery, not naming convention:
  An RPi3 is identified by `arch=arm64 AND memory<2Gi`. The repo's catalog
  metadata uses `tier: rpi3-only` (see k8s/apps/{adguard,unifi}/catalog-info.yaml)
  but that label is on the workload, not the node — so we discover by
  capability instead.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import pytest

HOG_NAMESPACE_PREFIX = "chaos-rpi3"
RPI3_MEMORY_CEILING_KI = 2 * 1024 * 1024  # 2 GiB in KiB
CRITICAL_NAMESPACES = {"adguard", "unifi"}

_FIXTURE_PATH = (
    Path(__file__).parent / "tests" / "fixtures" / "chaos" / "oom_hog_job.yaml"
)


# ── kubectl wrappers (light, to avoid a hard dep on _k8s_helpers in CLI) ─


def _kubectl_json(*args: str) -> dict:
    """Run `kubectl ... -o json` and parse the stdout."""
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def _kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", *args], check=check, text=True)


# ── public helpers ──────────────────────────────────────────────────────


def find_rpi3_node() -> Optional[str]:
    """Return the first node matching arch=arm64 AND memory<2Gi.

    Returns None if no RPi3-class node exists. Tests should pytest.skip
    on None (cluster-portable behavior).
    """
    nodes = _kubectl_json("get", "nodes")
    for n in nodes.get("items", []):
        arch = n.get("status", {}).get("nodeInfo", {}).get("architecture", "")
        mem_raw = n.get("status", {}).get("capacity", {}).get("memory", "0Ki")
        try:
            mem_ki = int(mem_raw.rstrip("Ki"))
        except ValueError:
            continue
        if arch == "arm64" and mem_ki < RPI3_MEMORY_CEILING_KI:
            return n["metadata"]["name"]
    return None


def assert_no_critical_workloads(node_name: str) -> None:
    """Refuse to chaos a node currently hosting production DNS or UniFi.

    Raises pytest.skip — chaos is opt-in and never worth taking down home
    DNS for users. Drain the workloads first, or run on a fresh cluster.
    """
    pods = _kubectl_json("get", "pods", "-A")
    hits = [
        p["metadata"]["namespace"] + "/" + p["metadata"]["name"]
        for p in pods.get("items", [])
        if p.get("spec", {}).get("nodeName") == node_name
        and p["metadata"]["namespace"] in CRITICAL_NAMESPACES
    ]
    if hits:
        pytest.skip(
            f"Refusing chaos on {node_name}: critical pods present {hits}. "
            f"Drain {sorted(CRITICAL_NAMESPACES)} or run on a non-prod cluster."
        )


def apply_chaos_manifests(namespace: str, target_node: str) -> None:
    """Render the fixture YAML with namespace+node substitutions and apply."""
    manifest = _FIXTURE_PATH.read_text()
    rendered = manifest.replace("__NAMESPACE__", namespace).replace(
        "__TARGET_NODE__", target_node
    )
    subprocess.run(
        ["kubectl", "apply", "-f", "-"], input=rendered, text=True, check=True
    )


def cleanup_chaos_namespace(namespace: str) -> None:
    """Best-effort teardown — never raise from teardown path."""
    subprocess.run(
        [
            "kubectl",
            "delete",
            "namespace",
            namespace,
            "--ignore-not-found=true",
            "--wait=false",
        ],
        capture_output=True,
        text=True,
    )


def get_pod_status(namespace: str, label_selector: str) -> Optional[dict]:
    """Return the first matching pod's `.status` dict + nodeName.

    Returns None if no pod matches yet. The shape is:
      {"phase": ..., "nodeName": ..., "containerStatuses": [...]}
    """
    result = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            label_selector,
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    items = json.loads(result.stdout).get("items") or []
    if not items:
        return None
    pod = items[0]
    status = dict(pod.get("status", {}))
    status["nodeName"] = pod.get("spec", {}).get("nodeName")
    return status


def get_node_condition(node_name: str, condition_type: str) -> str:
    """Return the `.status` value (True/False/Unknown) for a node condition.

    Returns empty string if the node or condition is missing.
    """
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "node",
            node_name,
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    obj = json.loads(result.stdout)
    for c in obj.get("status", {}).get("conditions", []):
        if c.get("type") == condition_type:
            return c.get("status", "")
    return ""


def list_argocd_apps_unhealthy(exclude_namespace: str = "") -> list[str]:
    """Return names of ArgoCD Applications whose health != Healthy.

    Apps whose `.spec.destination.namespace == exclude_namespace` are
    omitted — used to exclude the chaos namespace's own (expected-degraded)
    app from the collateral-damage check.
    """
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "applications.argoproj.io",
            "-A",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    items = json.loads(result.stdout).get("items") or []
    out: list[str] = []
    for app in items:
        dest_ns = app.get("spec", {}).get("destination", {}).get("namespace", "")
        if exclude_namespace and dest_ns == exclude_namespace:
            continue
        health = app.get("status", {}).get("health", {}).get("status", "")
        if health not in ("Healthy", ""):
            out.append(app["metadata"]["name"])
    return out


def prometheus_oomkill_observed(
    prometheus_url: str, namespace: str, pod_pattern: str
) -> bool:
    """Query Prometheus for `kube_pod_container_status_last_terminated_reason`.

    Returns True if at least one series exists with reason="OOMKilled" for a
    pod matching `pod_pattern` in `namespace`. Returns False on query error
    (caller decides whether absence is a test failure).
    """
    expr = (
        f"kube_pod_container_status_last_terminated_reason"
        f'{{reason="OOMKilled",namespace="{namespace}",pod=~"{pod_pattern}"}}'
    )
    qs = urllib.parse.urlencode({"query": expr})
    url = f"{prometheus_url.rstrip('/')}/api/v1/query?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    if body.get("status") != "success":
        return False
    return bool(body.get("data", {}).get("result"))


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trigger an RPi3 OOM chaos drill (manual debug tool).",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Tear down a previously-created chaos namespace and exit.",
    )
    parser.add_argument(
        "--namespace",
        help="Target namespace (default: auto-generated chaos-rpi3-<ts>).",
    )
    args = parser.parse_args(argv)

    if not shutil.which("kubectl"):
        print("kubectl not on PATH", file=sys.stderr)
        return 2

    if args.cleanup_only:
        if not args.namespace:
            print("--cleanup-only requires --namespace", file=sys.stderr)
            return 2
        cleanup_chaos_namespace(args.namespace)
        return 0

    node = find_rpi3_node()
    if node is None:
        print("no RPi3-class node found; nothing to do", file=sys.stderr)
        return 0
    pods = _kubectl_json("get", "pods", "-A")
    blockers = [
        p["metadata"]["namespace"] + "/" + p["metadata"]["name"]
        for p in pods.get("items", [])
        if p.get("spec", {}).get("nodeName") == node
        and p["metadata"]["namespace"] in CRITICAL_NAMESPACES
    ]
    if blockers:
        print(
            f"refusing chaos on {node}: critical pods present: {blockers}",
            file=sys.stderr,
        )
        return 1
    import time as _time

    ns = args.namespace or f"{HOG_NAMESPACE_PREFIX}-{int(_time.time())}"
    print(f"starting OOM drill: node={node} namespace={ns}")
    apply_chaos_manifests(ns, node)
    print(f"manifests applied; observe with: kubectl -n {ns} get pods -w")
    print(
        f"clean up with: python3 -m bin.chaos_rpi3_oom --cleanup-only --namespace {ns}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
