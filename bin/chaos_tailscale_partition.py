"""Tailscale mesh-partition fault injector — helpers + thin CLI.

Companion to `bin/tests/test_chaos_tailscale_partition.py`. The helpers
expose every primitive the test asserts on (mesh status, node readiness,
graceful recovery), so the assertions in the test stay declarative.

Safety: `assert_target_is_safe(host)` refuses to run against a host whose
hostname looks like an RPi3 — the Tailscale agent's RSS is comparable to
the RPi3's free memory ceiling and we don't want chaos to OOM the test
target. Use RPi4 or AWS as the chaos victim. CHAOS_TAILSCALE_ACK and the
ephemeral auth key are enforced by the Makefile target, not here.

SSH transport: shells out to `ssh <host> sudo tailscale ...`. The runner
must already have an SSH agent or key configured (the existing preflight
checks in `bin/preflight.py` validate that).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from typing import Optional

import pytest

RPI3_HOSTNAME_PATTERNS = (
    re.compile(r"rasp.*pi.*0?3", re.IGNORECASE),
    re.compile(r"rpi-?3", re.IGNORECASE),
)
DEFAULT_NODE_GRACE_PERIOD = 40  # k3s default in seconds


# ── ssh wrappers ─────────────────────────────────────────────────────────


def _ssh(host: str, *cmd: str, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a remote command via SSH. Caller decides whether to capture stdout."""
    full = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        host,
        *cmd,
    ]
    if capture:
        return subprocess.run(full, capture_output=True, text=True, check=False)
    return subprocess.run(full, text=True, check=False)


def _kubectl_json(*args: str) -> dict:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


# ── safety guards ────────────────────────────────────────────────────────


def assert_target_is_safe(host: str) -> None:
    """Refuse chaos against any host whose name suggests it's the RPi3.

    This is belt-and-suspenders — the chaos test should also be invoked
    against RPi4 or AWS hosts only. Hostname pattern matching is
    intentionally permissive: false positives just make us safer.
    """
    for pat in RPI3_HOSTNAME_PATTERNS:
        if pat.search(host):
            pytest.skip(
                f"Refusing chaos on {host!r}: hostname matches RPi3 pattern. "
                f"Tailscale chaos belongs on RPi4 or AWS only."
            )


# ── observation ──────────────────────────────────────────────────────────


def get_tailscale_status(host: str) -> dict:
    """Return parsed `tailscale status --json` summary for a remote host.

    Shape:
      {
        "self_online": bool,
        "control_plane_peers_online": int,
        "max_peer_handshake_age_seconds": float,
      }
    """
    res = _ssh(host, "sudo", "tailscale", "status", "--json", capture=True)
    if res.returncode != 0:
        return {
            "self_online": False,
            "control_plane_peers_online": 0,
            "max_peer_handshake_age_seconds": float("inf"),
        }
    try:
        obj = json.loads(res.stdout)
    except json.JSONDecodeError:
        return {
            "self_online": False,
            "control_plane_peers_online": 0,
            "max_peer_handshake_age_seconds": float("inf"),
        }
    self_online = bool(obj.get("Self", {}).get("Online"))
    peers = list((obj.get("Peer") or {}).values())
    control_plane = sum(
        1
        for p in peers
        if p.get("Online") and "k3s-server" in (p.get("HostName") or "").lower()
    )
    if control_plane == 0:
        # Fallback: any online peer counts. The repo's prod doesn't tag
        # hosts as k3s-server in Tailscale machine names, so the strict
        # match is best-effort.
        control_plane = sum(1 for p in peers if p.get("Online"))
    now = time.time()
    handshakes = []
    for p in peers:
        ts = p.get("LastHandshake")
        if not ts or ts.startswith("0001-01-01"):
            continue
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            handshakes.append(now - parsed)
        except (ValueError, TypeError):
            continue
    max_age = max(handshakes) if handshakes else 0.0
    return {
        "self_online": self_online,
        "control_plane_peers_online": control_plane,
        "max_peer_handshake_age_seconds": max_age,
    }


def get_node_ready_status(host: str) -> str:
    """Return the value of the node's `Ready` condition status (True/False/Unknown).

    Returns empty string if the node is not in the cluster.
    """
    try:
        obj = _kubectl_json("get", "node", host)
    except subprocess.CalledProcessError:
        return ""
    for c in obj.get("status", {}).get("conditions", []):
        if c.get("type") == "Ready":
            return c.get("status", "")
    return ""


def get_node_taints(host: str) -> list[str]:
    """Return the list of taint keys on a node (empty if untainted)."""
    try:
        obj = _kubectl_json("get", "node", host)
    except subprocess.CalledProcessError:
        return []
    return [t.get("key", "") for t in obj.get("spec", {}).get("taints") or []]


def get_node_grace_period_seconds(default: int = DEFAULT_NODE_GRACE_PERIOD) -> int:
    """Read the kubelet's --node-monitor-grace-period.

    Reads it from the kube-controller-manager pod spec when discoverable;
    otherwise falls back to the k3s default of 40s. We avoid hardcoding to
    survive a future KCM tuning change.
    """
    try:
        obj = _kubectl_json(
            "get",
            "pods",
            "-n",
            "kube-system",
            "-l",
            "component=kube-controller-manager",
        )
    except subprocess.CalledProcessError:
        return default
    items = obj.get("items") or []
    if not items:
        return default
    containers = items[0].get("spec", {}).get("containers") or []
    for c in containers:
        for arg in c.get("args", []) or c.get("command", []):
            if arg.startswith("--node-monitor-grace-period="):
                value = arg.split("=", 1)[1]
                # value formats: "40s", "0h1m0s"
                m = re.match(r"^(\d+)s$", value)
                if m:
                    return int(m.group(1))
                m = re.match(r"^(\d+)m(\d+)s$", value)
                if m:
                    return int(m.group(1)) * 60 + int(m.group(2))
    return default


def sample_workload_restarts(exclude_node: str = "") -> dict[str, int]:
    """Snapshot `restartCount` for each container on each non-excluded pod.

    Key: "<namespace>/<pod>/<container>". Used to compute deltas across the
    partition window. Excludes the chaos-target node so its expected pod
    disruption doesn't dominate the assertion.
    """
    try:
        obj = _kubectl_json("get", "pods", "-A")
    except subprocess.CalledProcessError:
        return {}
    out: dict[str, int] = {}
    for pod in obj.get("items", []):
        node = pod.get("spec", {}).get("nodeName", "")
        if exclude_node and node == exclude_node:
            continue
        ns = pod["metadata"]["namespace"]
        name = pod["metadata"]["name"]
        for cs in pod.get("status", {}).get("containerStatuses") or []:
            key = f"{ns}/{name}/{cs.get('name', '')}"
            out[key] = int(cs.get("restartCount", 0))
    return out


# ── action ───────────────────────────────────────────────────────────────


def bring_tailscale_down(host: str) -> None:
    """`ssh <host> sudo tailscale down` — raises on SSH failure."""
    res = _ssh(host, "sudo", "tailscale", "down", capture=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"failed to bring tailscale down on {host}: rc={res.returncode}\n"
            f"stderr: {res.stderr}"
        )


def bring_tailscale_up(host: str, auth_key: str) -> None:
    """`ssh <host> sudo tailscale up --authkey=...` — best-effort, never raises.

    Recovery is best-effort by design: we want the test's `finally` block
    to always succeed enough that the cluster lands back in a usable state
    even if the assertions above failed first.
    """
    _ssh(
        host,
        "sudo",
        "tailscale",
        "up",
        f"--authkey={auth_key}",
        "--reset",
        capture=True,
    )


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tailscale partition fault-injection helper (manual debug tool).",
    )
    parser.add_argument("host", help="SSH-reachable hostname of the chaos victim")
    parser.add_argument(
        "action",
        choices=("status", "down", "up"),
        help="Observe (status) or mutate (down/up) the mesh.",
    )
    parser.add_argument(
        "--auth-key",
        default=None,
        help="Tailscale ephemeral auth key (required for 'up').",
    )
    args = parser.parse_args(argv)

    assert_target_is_safe(args.host)

    if args.action == "status":
        print(json.dumps(get_tailscale_status(args.host), indent=2))
        return 0
    if args.action == "down":
        bring_tailscale_down(args.host)
        print(f"tailscale down OK on {args.host}")
        return 0
    if args.action == "up":
        if not args.auth_key:
            print("--auth-key required for 'up'", file=sys.stderr)
            return 2
        bring_tailscale_up(args.host, args.auth_key)
        print(f"tailscale up OK on {args.host}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
