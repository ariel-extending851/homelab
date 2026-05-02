"""RPi3 OOM resilience drill — assert the 1GB ARM64 node fails gracefully.

Marked `@pytest.mark.live, @pytest.mark.chaos`. Skipped unless `--run-live`
is passed AND the Makefile target's CHAOS_ACK env var is set.

Run via:
  CHAOS_ACK=I_ACCEPT_THE_RISK make test-chaos-rpi3

What the test asserts (the resilience contract):

  1. The hog Job actually lands on the RPi3-class node we discovered.
  2. The hog container is OOMKilled (terminal reason on lastState).
  3. The Job restartCount climbs ≥2 — kubelet retried, didn't give up early.
  4. A sentinel pod on the same node is unaffected: no restart, stays Ready.
  5. Node MemoryPressure recovers to False within 60s of Job completion.
  6. Prometheus kube-state-metrics observed the OOMKill (data path proven).
  7. ArgoCD Apps unrelated to the chaos namespace stay Healthy throughout.

The pre-flight `assert_no_critical_workloads` guard refuses to run if the
selected node currently hosts any pod from `adguard` or `unifi` namespaces
— those are the production DNS and network admin workloads pinned to the
RPi3 by `tier: rpi3-only` catalog metadata. Drain them first, or run on
a non-prod cluster.
"""

from __future__ import annotations

import os
import time

import pytest

from bin.chaos_rpi3_oom import (
    HOG_NAMESPACE_PREFIX,
    apply_chaos_manifests,
    assert_no_critical_workloads,
    cleanup_chaos_namespace,
    find_rpi3_node,
    get_node_condition,
    get_pod_status,
    list_argocd_apps_unhealthy,
    prometheus_oomkill_observed,
)
from bin.tests._k8s_helpers import _kubectl, wait_for

pytestmark = [pytest.mark.live, pytest.mark.chaos]

OOM_TIMEOUT = int(os.environ.get("OOM_TIMEOUT", "60"))
RECOVERY_TIMEOUT = int(os.environ.get("RECOVERY_TIMEOUT", "60"))
PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL", "http://prometheus.monitoring.svc:9090"
)


@pytest.fixture(scope="module")
def rpi3_node() -> str:
    """Discover an RPi3-class node by capability (arm64 + <2Gi RAM).

    Skips the suite if no such node exists in the cluster — keeps the test
    portable across the prod cluster, k3d local, and CI clusters that
    don't include an RPi3.
    """
    node = find_rpi3_node()
    if node is None:
        pytest.skip("no RPi3-class node (arm64, <2Gi RAM) in this cluster")
    return node


@pytest.fixture(scope="module")
def chaos_namespace(rpi3_node: str):
    """Create chaos-rpi3-<suffix> namespace; tear down on exit.

    Pre-flight: refuses if production-critical pods are scheduled on the
    target node. This is a hard guard — even with CHAOS_ACK set the test
    will skip rather than knock out home DNS.
    """
    assert_no_critical_workloads(rpi3_node)
    ns = f"{HOG_NAMESPACE_PREFIX}-{int(time.time())}"
    try:
        yield ns
    finally:
        cleanup_chaos_namespace(ns)


def test_rpi3_node_discovered(rpi3_node: str) -> None:
    """Sanity: the cluster actually has an RPi3-class node visible to us."""
    assert rpi3_node, "find_rpi3_node returned empty string"


def test_oom_drill_full_cycle(rpi3_node: str, chaos_namespace: str) -> None:
    """End-to-end OOM resilience contract — all 7 assertions in one test.

    A single test (rather than seven) because the assertions share state
    (the chaos namespace, the hog Job, observation timestamps) and the
    failure modes only make sense in sequence — e.g. assertion 5 about
    MemoryPressure recovery is meaningless if assertion 2 (OOMKilled)
    didn't trigger.
    """
    apply_chaos_manifests(chaos_namespace, rpi3_node)

    # Capture the unrelated-app baseline BEFORE chaos so we can compare deltas.
    unhealthy_before = set(
        list_argocd_apps_unhealthy(exclude_namespace=chaos_namespace)
    )

    # ── 1. hog scheduled onto RPi3 node ────────────────────────────────────
    def hog_scheduled() -> bool:
        status = get_pod_status(chaos_namespace, "app.kubernetes.io/name=oom-hog")
        return bool(status and status.get("nodeName") == rpi3_node)

    wait_for(hog_scheduled, timeout=60, interval=2.0)
    hog = get_pod_status(chaos_namespace, "app.kubernetes.io/name=oom-hog")
    assert (
        hog["nodeName"] == rpi3_node
    ), f"hog pod scheduled to {hog['nodeName']!r}, expected {rpi3_node!r}"

    # ── 2. container terminated with reason=OOMKilled ──────────────────────
    def saw_oomkill() -> bool:
        status = get_pod_status(chaos_namespace, "app.kubernetes.io/name=oom-hog")
        for cs in (status or {}).get("containerStatuses", []) or []:
            last = (cs.get("lastState") or {}).get("terminated") or {}
            if last.get("reason") == "OOMKilled":
                return True
        return False

    wait_for(saw_oomkill, timeout=OOM_TIMEOUT, interval=2.0)

    # ── 3. restartCount climbed ≥ 2 (kubelet retried) ──────────────────────
    final = get_pod_status(chaos_namespace, "app.kubernetes.io/name=oom-hog")
    restarts = (final.get("containerStatuses") or [{}])[0].get("restartCount", 0)
    assert restarts >= 2, f"expected restartCount >= 2, got {restarts}"

    # ── 4. sentinel pod on same node unaffected ────────────────────────────
    sentinel = get_pod_status(chaos_namespace, "app.kubernetes.io/name=sentinel")
    assert sentinel, "sentinel pod missing"
    assert (
        sentinel.get("phase") == "Running"
    ), f"sentinel not Running: phase={sentinel.get('phase')}"
    sentinel_restarts = (sentinel.get("containerStatuses") or [{}])[0].get(
        "restartCount", 0
    )
    assert (
        sentinel_restarts == 0
    ), f"sentinel restarted ({sentinel_restarts}) — OOM was not contained"

    # ── 5. MemoryPressure recovered ────────────────────────────────────────
    def memory_pressure_clear() -> bool:
        return get_node_condition(rpi3_node, "MemoryPressure") in {"False", ""}

    wait_for(memory_pressure_clear, timeout=RECOVERY_TIMEOUT, interval=3.0)

    # ── 6. Prometheus saw the OOMKill (data path) ──────────────────────────
    assert prometheus_oomkill_observed(
        prometheus_url=PROMETHEUS_URL,
        namespace=chaos_namespace,
        pod_pattern="oom-hog.*",
    ), "kube-state-metrics did not record OOMKilled for oom-hog* pods"

    # ── 7. unrelated ArgoCD apps remained healthy ──────────────────────────
    unhealthy_after = set(list_argocd_apps_unhealthy(exclude_namespace=chaos_namespace))
    new_unhealthy = unhealthy_after - unhealthy_before
    assert (
        not new_unhealthy
    ), f"chaos induced collateral damage in ArgoCD apps: {sorted(new_unhealthy)}"
