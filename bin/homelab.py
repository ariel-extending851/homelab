#!/usr/bin/env python3
"""homelab — unified diagnostics CLI for the homelab repo.

Thin wrapper that reuses logic already shipped in bin/drift.py,
bin/smoke_test.py, and bin/preflight.py — providing a single entry point
for common debugging tasks during and after a deploy.

Sub-commands:
    homelab argocd diagnose <app>    Inspect an ArgoCD application's
                                     sync/health/conditions and surface
                                     the most recent error message.
    homelab tf drift [--summary]     Run the Terraform drift probe from
                                     bin/drift.py with Argo + inventory
                                     checks skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import drift  # noqa: E402
import morning_sync  # noqa: E402
import smoke_test  # noqa: E402


def _kubectl(
    argv: list[str], kubeconfig: str | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    cmd = ["kubectl", *argv]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)


# ── argocd diagnose ──────────────────────────────────────────────────────────


def cmd_argocd_diagnose(args: argparse.Namespace) -> int:
    """Print sync/health/conditions for one ArgoCD application."""
    res = _kubectl(
        ["get", "application", args.app, "-n", args.namespace, "-o", "json"],
        kubeconfig=args.kubeconfig,
    )
    if res.returncode != 0:
        print(f"❌ kubectl failed: {res.stderr.strip()}", file=sys.stderr)
        return 2
    return render_argocd_diagnose(res.stdout, sys.stdout)


def render_argocd_diagnose(stdout: str, out) -> int:
    """Format ArgoCD application JSON; returns shell exit code."""
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError as e:
        print(f"❌ invalid JSON from kubectl: {e}", file=sys.stderr)
        return 2

    name = data.get("metadata", {}).get("name", "<unknown>")
    sync = data.get("status", {}).get("sync", {}).get("status", "Unknown")
    health = data.get("status", {}).get("health", {}).get("status", "Unknown")
    conditions = data.get("status", {}).get("conditions") or []
    operation = data.get("status", {}).get("operationState") or {}

    out.write(f"App: {name}\n")
    out.write(f"  Sync:   {sync}\n")
    out.write(f"  Health: {health}\n")

    if conditions:
        out.write("  Conditions:\n")
        for c in conditions:
            out.write(f"    [{c.get('type', '?')}] {c.get('message', '').strip()}\n")
    else:
        out.write("  Conditions: (none)\n")

    op_phase = operation.get("phase")
    op_msg = (operation.get("message") or "").strip()
    if op_phase or op_msg:
        out.write(f"  Last operation: {op_phase or '?'}")
        if op_msg:
            out.write(f" — {op_msg}")
        out.write("\n")

    if sync == "Synced" and health == "Healthy" and not conditions:
        return 0
    return 1


# ── argocd list ──────────────────────────────────────────────────────────────


def cmd_argocd_list(args: argparse.Namespace) -> int:
    """List ArgoCD applications with sync + health status."""
    res = _kubectl(
        ["get", "applications", "-n", args.namespace, "-o", "json"],
        kubeconfig=args.kubeconfig,
    )
    if res.returncode != 0:
        print(f"❌ kubectl failed: {res.stderr.strip()}", file=sys.stderr)
        return 2
    return render_argocd_list(res.stdout, sys.stdout)


def render_argocd_list(stdout: str, out) -> int:
    apps = smoke_test.parse_argocd_apps(stdout)
    if not apps:
        out.write("No ArgoCD applications found.\n")
        return 1
    out.write(f"{'NAME':<30} {'SYNC':<12} {'HEALTH':<12}\n")
    drift_count = 0
    for app in apps:
        out.write(f"{app.name:<30} {app.sync_status:<12} {app.health_status:<12}\n")
        if app.sync_status != "Synced" or app.health_status != "Healthy":
            drift_count += 1
    out.write(f"\nTotal: {len(apps)} apps, {drift_count} not Synced+Healthy\n")
    return 0 if drift_count == 0 else 1


# ── k3s status ───────────────────────────────────────────────────────────────


def cmd_k3s_status(args: argparse.Namespace) -> int:
    """Show k3s node status — wrapper over morning_sync's node parsing."""
    res = _kubectl(
        ["get", "nodes", "--no-headers", "-o", "wide"],
        kubeconfig=args.kubeconfig,
    )
    if res.returncode != 0:
        print(f"❌ kubectl failed: {res.stderr.strip()}", file=sys.stderr)
        return 2
    return render_k3s_status(res.stdout, sys.stdout)


def render_k3s_status(stdout: str, out) -> int:
    nodes = morning_sync.parse_kubectl_nodes(stdout)
    if not nodes:
        out.write("No nodes found.\n")
        return 1
    out.write(f"{'NAME':<25} {'STATUS':<12} {'ROLES':<25}\n")
    not_ready = 0
    for name, status, roles in nodes:
        out.write(f"{name:<25} {status:<12} {roles:<25}\n")
        if status != "Ready":
            not_ready += 1
    out.write(f"\nTotal: {len(nodes)} nodes, {not_ready} not Ready\n")
    return 0 if not_ready == 0 else 1


# ── ci replay ────────────────────────────────────────────────────────────────


CI_REPLAY_TARGETS = {
    "smoke-test": "Run post-deploy smoke tests (20+ checks)",
    "test-e2e-post-deploy": "Run BATS e2e suite (40+ tests)",
    "validate-argocd-synced": "Wait for ArgoCD root app to converge",
    "validate-terraform-all": "Validate all Terraform configurations",
    "test-ansible-idempotency": "Verify Molecule idempotence coverage",
    "test-velero-restore": "Validate Velero backup → restore",
    "terraform-cost-diff": "Run Infracost diff against baseline",
}


def cmd_ci_replay(args: argparse.Namespace) -> int:
    """Replay a CI step by invoking the corresponding `make` target locally."""
    if args.step not in CI_REPLAY_TARGETS:
        valid = ", ".join(sorted(CI_REPLAY_TARGETS))
        print(f"❌ Unknown step '{args.step}'. Valid: {valid}", file=sys.stderr)
        return 2
    repo_root = BIN_DIR.parent
    print(f"▶ Running: make {args.step} (cwd={repo_root})")
    return subprocess.call(["make", args.step], cwd=repo_root)


# ── tf cost ──────────────────────────────────────────────────────────────────


def cmd_tf_cost(args: argparse.Namespace) -> int:
    """Show current Infracost breakdown for the live Terraform configuration."""
    repo_root = BIN_DIR.parent
    return subprocess.call(["make", "show-costs"], cwd=repo_root)


# ── tf drift ─────────────────────────────────────────────────────────────────


def cmd_tf_drift(args: argparse.Namespace) -> int:
    """Run the Terraform drift probe via bin/drift.py.

    Reuses drift.Drift but disables Argo + inventory checks. With
    --summary, emits a single line; otherwise prints the standard report.
    """
    drift_args = SimpleNamespace(
        skip_tf=False,
        skip_argo=True,
        skip_inventory=True,
        output="text",
        kubeconfig=args.kubeconfig,
        timeout=args.timeout,
        fix=False,
        no_fix=True,
    )
    d = drift.Drift(drift_args)
    d.check_terraform()

    tf_check = next(
        (c for c in d.checks if c["name"] == "tf.drift"),
        {"status": "skip", "message": ""},
    )

    if args.summary:
        status = tf_check["status"]
        message = tf_check["message"]
        icon = {"pass": "✓", "fail": "✗", "warn": "⚠", "skip": "—"}.get(status, "?")
        print(f"{icon} tf.drift: {status} — {message}")
    else:
        d.render(sys.stdout)

    return 0 if tf_check["status"] in {"pass", "skip"} else 1


# ── arg parser ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="homelab",
        description="Homelab diagnostics CLI",
    )
    sub = p.add_subparsers(dest="group", required=True)

    argocd_parser = sub.add_parser("argocd", help="ArgoCD operations")
    argocd_sub = argocd_parser.add_subparsers(dest="cmd", required=True)
    diag = argocd_sub.add_parser("diagnose", help="Inspect an ArgoCD application")
    diag.add_argument("app", help="Application name (e.g. root, grafana)")
    diag.add_argument(
        "--namespace", "-n", default="argocd", help="ArgoCD namespace (default: argocd)"
    )
    diag.add_argument("--kubeconfig", default=None, help="Path to kubeconfig")
    diag.set_defaults(func=cmd_argocd_diagnose)

    lst = argocd_sub.add_parser("list", help="List ArgoCD apps with sync/health")
    lst.add_argument(
        "--namespace", "-n", default="argocd", help="ArgoCD namespace (default: argocd)"
    )
    lst.add_argument("--kubeconfig", default=None, help="Path to kubeconfig")
    lst.set_defaults(func=cmd_argocd_list)

    tf_parser = sub.add_parser("tf", help="Terraform operations")
    tf_sub = tf_parser.add_subparsers(dest="cmd", required=True)
    drift_p = tf_sub.add_parser("drift", help="Detect Terraform drift")
    drift_p.add_argument(
        "--summary",
        action="store_true",
        help="Print one-line summary instead of full report",
    )
    drift_p.add_argument(
        "--kubeconfig",
        default=None,
        help="Path to kubeconfig (unused; kept for future Argo integration)",
    )
    drift_p.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-command timeout in seconds (default: 60)",
    )
    drift_p.set_defaults(func=cmd_tf_drift)

    cost_p = tf_sub.add_parser(
        "cost", help="Show Infracost breakdown for prod (calls make show-costs)"
    )
    cost_p.set_defaults(func=cmd_tf_cost)

    k3s_parser = sub.add_parser("k3s", help="k3s cluster operations")
    k3s_sub = k3s_parser.add_subparsers(dest="cmd", required=True)
    k3s_status = k3s_sub.add_parser("status", help="Show node status")
    k3s_status.add_argument("--kubeconfig", default=None, help="Path to kubeconfig")
    k3s_status.set_defaults(func=cmd_k3s_status)

    ci_parser = sub.add_parser("ci", help="Replay CI steps locally")
    ci_sub = ci_parser.add_subparsers(dest="cmd", required=True)
    replay = ci_sub.add_parser(
        "replay",
        help="Run a CI step locally as `make <step>`",
        description="Available steps:\n  "
        + "\n  ".join(
            f"{name:<30} {desc}" for name, desc in sorted(CI_REPLAY_TARGETS.items())
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    replay.add_argument("step", help="Make target name to replay (see help)")
    replay.set_defaults(func=cmd_ci_replay)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
