#!/usr/bin/env python3
"""Morning sync — daily homelab health check.

Runs the existing smoke tests, checks Tailscale VPN node status, verifies all
K3s nodes are Ready, and scans the last N lines of Loki logs for ERROR/FATAL
messages, then prints a 3-bullet health summary.

Usage:
  KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml python3 bin/morning_sync.py
  python3 bin/morning_sync.py --kubeconfig ~/.kube/config
  python3 bin/morning_sync.py --skip-tailscale --loki-tail 100

Exit codes:
  0  everything healthy
  1  critical failure (K3s node not Ready, smoke test failed)
  2  warnings only (peer offline, Loki errors, minor app issues)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN))

from preflight import parse_tailscale_status  # noqa: E402
from smoke_test import SmokeTest  # noqa: E402

KUBECONFIG_DEFAULT = "/tmp/k3s-homelab-kubeconfig.yaml"
_SEP = "─" * 62
_DBL = "═" * 62


# ── result container ─────────────────────────────────────────────────────────


class SyncResult:
    def __init__(self):
        self.smoke_exit = None
        self.smoke_failures = 0
        self.smoke_app_failures = 0

        self.ts_state = ""
        self.ts_peers_online = 0
        self.ts_peers_total = 0
        self.ts_nodes = []
        self.ts_error = ""

        self.k3s_nodes = []
        self.k3s_not_ready = []
        self.k3s_error = ""

        self.loki_error_count = 0
        self.loki_fatal_count = 0
        self.loki_samples = []
        self.loki_error = ""


# ── parsing helpers (pure functions — contract-testable) ─────────────────────


def parse_kubectl_nodes(stdout):
    """Parse ``kubectl get nodes --no-headers -o wide`` output.

    Columns: NAME  STATUS  ROLES  AGE  VERSION  INTERNAL-IP ...
    Returns [(name, status, roles)] for each non-blank line with ≥3 tokens.
    """
    nodes = []
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        nodes.append((parts[0], parts[1], parts[2]))
    return nodes


def parse_tailscale_peers(stdout):
    """Return [(hostname, online)] from ``tailscale status --json``.

    Returns [] on blank / malformed input.
    """
    if not (stdout or "").strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    peers = data.get("Peer") or {}
    result = []
    for peer in peers.values():
        if not isinstance(peer, dict):
            continue
        hostname = peer.get("HostName") or peer.get("DNSName") or "(unknown)"
        result.append((hostname, bool(peer.get("Online"))))
    return result


# ── section banner ────────────────────────────────────────────────────────────


def _section(title):
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


# ── helpers ───────────────────────────────────────────────────────────────────


def _kubectl(kubeconfig, args, timeout=20):
    env = os.environ.copy()
    env["KUBECONFIG"] = kubeconfig
    return subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


# ── 1. Smoke tests ────────────────────────────────────────────────────────────


def run_smoke_tests(kubeconfig, result):
    _section("Smoke Tests")
    st = SmokeTest(kubeconfig=kubeconfig)
    exit_code = st.run()
    result.smoke_exit = exit_code
    result.smoke_failures = st.failed
    result.smoke_app_failures = st.apps_failed


# ── 2. Tailscale VPN node status ──────────────────────────────────────────────


def check_tailscale(result):
    _section("Tailscale VPN Nodes")
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        result.ts_error = "tailscale CLI not found on PATH"
        print(f"  ✗ {result.ts_error}")
        return
    except subprocess.TimeoutExpired:
        result.ts_error = "tailscale status timed out"
        print(f"  ✗ {result.ts_error}")
        return

    if r.returncode != 0:
        result.ts_error = (
            (r.stderr or "tailscale status failed").strip().splitlines()[0]
        )
        print(f"  ✗ {result.ts_error}")
        return

    state, online = parse_tailscale_status(r.stdout)
    nodes = parse_tailscale_peers(r.stdout)

    result.ts_state = state
    result.ts_nodes = nodes
    result.ts_peers_online = online
    result.ts_peers_total = len(nodes)

    state_icon = "✓" if state == "Running" else "✗"
    print(f"  {state_icon} Backend: {state or '(unknown)'}")
    peer_icon = "✓" if online == len(nodes) else "⚠"
    print(f"  {peer_icon} Peers: {online}/{len(nodes)} online")
    for hostname, is_online in sorted(nodes):
        dot = "●" if is_online else "○"
        print(f"      {dot} {hostname}")


# ── 3. K3s node readiness ─────────────────────────────────────────────────────


def check_k3s_nodes(kubeconfig, result):
    _section("K3s Node Readiness")
    try:
        r = _kubectl(
            kubeconfig,
            ["--request-timeout=10s", "get", "nodes", "--no-headers", "-o", "wide"],
        )
    except FileNotFoundError:
        result.k3s_error = "kubectl not found on PATH"
        print(f"  ✗ {result.k3s_error}")
        return
    except subprocess.TimeoutExpired:
        result.k3s_error = "kubectl get nodes timed out"
        print(f"  ✗ {result.k3s_error}")
        return

    if r.returncode != 0:
        result.k3s_error = (
            (r.stderr or "kubectl get nodes failed").strip().splitlines()[0]
        )
        print(f"  ✗ {result.k3s_error}")
        return

    nodes = parse_kubectl_nodes(r.stdout)
    result.k3s_nodes = nodes
    result.k3s_not_ready = [name for name, status, _ in nodes if status != "Ready"]

    if not nodes:
        result.k3s_error = "no nodes returned — check KUBECONFIG"
        print(f"  ⚠ {result.k3s_error}")
        return

    for name, status, roles in nodes:
        icon = "✓" if status == "Ready" else "✗"
        print(f"  {icon} {name:<32} {status:<12} roles={roles}")

    if not result.k3s_not_ready:
        print(f"\n  ✓ All {len(nodes)} node(s) Ready")
    else:
        print(
            f"\n  ✗ {len(result.k3s_not_ready)} node(s) NOT Ready: {', '.join(result.k3s_not_ready)}"
        )


# ── 4. Loki log scan ──────────────────────────────────────────────────────────


def check_loki_logs(kubeconfig, result, tail=50):
    _section(f"Loki Logs  (last {tail} lines — ERROR/FATAL scan)")
    try:
        r = _kubectl(
            kubeconfig,
            [
                "--request-timeout=15s",
                "logs",
                "-n",
                "monitoring",
                "deployment/loki",
                f"--tail={tail}",
            ],
            timeout=25,
        )
    except FileNotFoundError:
        result.loki_error = "kubectl not found on PATH"
        print(f"  ✗ {result.loki_error}")
        return
    except subprocess.TimeoutExpired:
        result.loki_error = "kubectl logs timed out"
        print(f"  ✗ {result.loki_error}")
        return

    if r.returncode != 0:
        result.loki_error = (r.stderr or "kubectl logs failed").strip().splitlines()[0]
        print(f"  ✗ {result.loki_error}")
        return

    lines = (r.stdout or "").splitlines()
    hits = [ln for ln in lines if "ERROR" in ln or "FATAL" in ln]
    result.loki_error_count = sum(1 for ln in hits if "ERROR" in ln)
    result.loki_fatal_count = sum(1 for ln in hits if "FATAL" in ln)
    result.loki_samples = hits[:3]

    if not hits:
        print(f"  ✓ No ERROR or FATAL messages in last {tail} lines")
    else:
        print(
            f"  ⚠ {len(hits)} issue(s): {result.loki_error_count} ERROR, "
            f"{result.loki_fatal_count} FATAL"
        )
        for sample in result.loki_samples:
            print(f"      → {sample[:120]}")
        if len(hits) > 3:
            print(f"      … and {len(hits) - 3} more")


# ── 5. 3-bullet summary ───────────────────────────────────────────────────────


def print_summary(result):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{_DBL}")
    print(f"  Morning Sync Summary  [{now}]")
    print(_DBL)

    # Bullet 1 — cluster / smoke tests
    if result.smoke_exit is None:
        b1 = "⚠  Cluster: smoke tests did not run (check KUBECONFIG)"
    elif result.smoke_exit == 0:
        b1 = "✓  Cluster: all smoke tests passed — cluster is production-ready"
    elif result.smoke_exit == 2:
        b1 = f"⚠  Cluster: {result.smoke_app_failures} app(s) degraded — minor issues"
    else:
        b1 = (
            f"✗  Cluster: {result.smoke_failures} check(s) failed, "
            f"{result.smoke_app_failures} app(s) degraded — INVESTIGATE"
        )

    # Bullet 2 — networking (Tailscale + K3s)
    ts_ok = result.ts_state == "Running" and (
        result.ts_peers_total == 0 or result.ts_peers_online == result.ts_peers_total
    )
    k3s_ok = (
        bool(result.k3s_nodes) and not result.k3s_not_ready and not result.k3s_error
    )

    if ts_ok and k3s_ok:
        b2 = (
            f"✓  Network: Tailscale Running "
            f"({result.ts_peers_online}/{result.ts_peers_total} peers online), "
            f"all {len(result.k3s_nodes)} K3s nodes Ready"
        )
    else:
        parts = []
        if result.ts_error:
            parts.append(f"Tailscale error — {result.ts_error}")
        elif result.ts_state != "Running":
            parts.append(f"Tailscale state={result.ts_state or 'unknown'}")
        elif result.ts_peers_online < result.ts_peers_total:
            parts.append(
                f"Tailscale {result.ts_peers_online}/{result.ts_peers_total} peers online"
            )
        if result.k3s_error:
            parts.append(f"K3s error — {result.k3s_error}")
        elif result.k3s_not_ready:
            parts.append(f"K3s not Ready: {', '.join(result.k3s_not_ready)}")
        icon = "✗" if (result.k3s_error or result.k3s_not_ready) else "⚠"
        b2 = f"{icon}  Network: {'; '.join(parts) or 'degraded — check logs above'}"

    # Bullet 3 — observability / Loki
    if result.loki_error:
        b3 = f"⚠  Logs: Loki unreachable ({result.loki_error})"
    elif result.loki_error_count == 0 and result.loki_fatal_count == 0:
        b3 = "✓  Logs: Loki clean — no ERROR or FATAL in last 50 lines"
    else:
        b3 = (
            f"⚠  Logs: Loki shows {result.loki_error_count} ERROR + "
            f"{result.loki_fatal_count} FATAL in last 50 lines — review above"
        )

    for bullet in (b1, b2, b3):
        print(f"  • {bullet}")
    print(f"{_DBL}\n")

    if result.smoke_exit == 1 or result.k3s_not_ready or result.k3s_error:
        return 1
    if (
        result.smoke_exit == 2
        or result.ts_peers_online < result.ts_peers_total
        or result.loki_fatal_count > 0
        or result.loki_error_count > 0
    ):
        return 2
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser():
    p = argparse.ArgumentParser(
        description="Morning sync — daily homelab health check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", KUBECONFIG_DEFAULT),
        help=f"path to kubeconfig (default: $KUBECONFIG or {KUBECONFIG_DEFAULT})",
    )
    p.add_argument(
        "--skip-tailscale",
        action="store_true",
        help="skip Tailscale VPN node check",
    )
    p.add_argument(
        "--loki-tail",
        type=int,
        default=50,
        metavar="N",
        help="number of Loki log lines to scan (default: 50)",
    )
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    result = SyncResult()

    print(f"🌅 Morning Sync  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   KUBECONFIG: {args.kubeconfig}")

    run_smoke_tests(args.kubeconfig, result)

    if args.skip_tailscale:
        print("\n  ⊘ Tailscale check skipped (--skip-tailscale)")
    else:
        check_tailscale(result)

    check_k3s_nodes(args.kubeconfig, result)
    check_loki_logs(args.kubeconfig, result, tail=args.loki_tail)

    return print_summary(result)


if __name__ == "__main__":
    sys.exit(main())
