"""Tailscale mesh-partition chaos drill — assert workload survival + auto-recovery.

Marked `@pytest.mark.live, @pytest.mark.chaos, @pytest.mark.disruptive`.
The `disruptive` marker is the trip-wire: this test cuts the VPN mesh on
the target node and never belongs on a schedule. Manual workflow_dispatch
only — see `.github/workflows/chaos-drill.yml`.

Required env (Makefile target `test-chaos-tailscale` enforces these):

  CHAOS_TAILSCALE_ACK=I_ACCEPT_THE_RISK
  TS_CHAOS_EPHEMERAL_AUTHKEY=<ephemeral key, expires after first use>
  TS_CHAOS_TARGET_HOST=<SSH-reachable hostname; must NOT be the RPi3>

What the test asserts (the recovery contract):

  1. Pre-condition: target is Online; at least one control-plane peer Online.
  2. Post-disconnect: node `Ready` condition flips to `Unknown` within
     `node-monitor-grace-period + 5s` (read live; never hard-coded).
  3. Workloads on *other* nodes show zero restart-count delta during the
     partition window.
  4. Post-reconnect: node returns to `Ready=True` within 90s.
  5. `Peer[*].LastHandshake` on the target is within 30s of test end —
     proves a freshly-negotiated session, not a stale cached handshake.
  6. No `node.kubernetes.io/network-unavailable` taint persists.
"""

from __future__ import annotations

import os

import pytest

from bin.chaos_tailscale_partition import (
    assert_target_is_safe,
    bring_tailscale_down,
    bring_tailscale_up,
    get_node_grace_period_seconds,
    get_node_ready_status,
    get_node_taints,
    get_tailscale_status,
    sample_workload_restarts,
)
from bin.tests._k8s_helpers import wait_for

pytestmark = [pytest.mark.live, pytest.mark.chaos, pytest.mark.disruptive]

RECONNECT_TIMEOUT = int(os.environ.get("RECONNECT_TIMEOUT", "90"))


@pytest.fixture(scope="module")
def target_host() -> str:
    host = os.environ.get("TS_CHAOS_TARGET_HOST")
    if not host:
        pytest.skip("TS_CHAOS_TARGET_HOST not set")
    assert_target_is_safe(host)  # refuses RPi3 + production-DNS hosts
    return host


@pytest.fixture(scope="module")
def auth_key() -> str:
    key = os.environ.get("TS_CHAOS_EPHEMERAL_AUTHKEY")
    if not key:
        pytest.skip("TS_CHAOS_EPHEMERAL_AUTHKEY not set")
    return key


def test_partition_recovery_cycle(target_host: str, auth_key: str) -> None:
    """End-to-end mesh-partition + recovery contract — single sequential test.

    Sequenced as one test because each assertion presupposes the prior
    state transition; splitting into six parametrized cases would make the
    failure mode harder to read, not easier.
    """

    # ── 1. pre-condition: target online, ≥1 control-plane peer online ───
    pre = get_tailscale_status(target_host)
    assert (
        pre["self_online"] is True
    ), f"target {target_host} not Online before chaos: {pre}"
    assert pre["control_plane_peers_online"] >= 1, (
        f"no control-plane peers Online for {target_host} — "
        f"refusing chaos against an already-degraded mesh"
    )

    # Snapshot baseline workload restart counts on non-target nodes.
    baseline = sample_workload_restarts(exclude_node=target_host)

    # ── kick off the partition ──────────────────────────────────────────
    bring_tailscale_down(target_host)
    try:
        # ── 2. node Ready transitions to Unknown within grace + 5s ──────
        grace = get_node_grace_period_seconds(default=40)
        deadline = grace + 5

        def ready_unknown() -> bool:
            return get_node_ready_status(target_host) in {"Unknown", "False"}

        wait_for(ready_unknown, timeout=deadline, interval=2.0)

        # ── 3. workloads on healthy nodes don't flap ────────────────────
        post_partition = sample_workload_restarts(exclude_node=target_host)
        for key, before in baseline.items():
            after = post_partition.get(key, before)
            assert after == before, (
                f"workload {key} restarted during partition "
                f"(before={before}, after={after}) — non-target node not isolated"
            )
    finally:
        # Always attempt recovery, even if assertions above failed.
        bring_tailscale_up(target_host, auth_key)

    # ── 4. node returns to Ready=True within RECONNECT_TIMEOUT ──────────
    def ready_true() -> bool:
        return get_node_ready_status(target_host) == "True"

    wait_for(ready_true, timeout=RECONNECT_TIMEOUT, interval=3.0)

    # ── 5. handshake is fresh (within 30s of "now") ─────────────────────
    post = get_tailscale_status(target_host)
    assert post["max_peer_handshake_age_seconds"] <= 30, (
        f"handshakes are stale ({post['max_peer_handshake_age_seconds']}s) — "
        f"mesh likely cached an old session"
    )

    # ── 6. no lingering NetworkUnavailable taint ────────────────────────
    taints = get_node_taints(target_host)
    bad = [t for t in taints if t.startswith("node.kubernetes.io/network-unavailable")]
    assert not bad, f"NetworkUnavailable taint persisted post-recovery: {bad}"
