#!/usr/bin/env python3
"""Take a Velero backup of the live cluster *before* a deploy modifies it.

Why pre-deploy and not the existing pre-test backup: Terraform can replace
EC2 instances mid-deploy (e.g., instance type change), wiping emptyDir +
ephemeral state. The post-deploy Velero restore test only proves the loop
works on the *new* cluster — it doesn't preserve the pre-deploy state to
roll back to.

Behavior:
  - If the cluster is unreachable (first deploy, or post-destroy), warn
    and exit 2 — non-blocking but loud (rollback safety reduced).
  - If Velero is not installed in the target cluster, warn and exit 2
    for the same reason.
  - Otherwise create `pre-deploy-<git-sha>-<unix-ts>` and wait up to
    --backup-timeout seconds for it to reach phase Completed.

Exit codes:
  0  backup completed
  1  hard failure (velero CLI missing, backup create failed, phase != Completed)
  2  skipped — backup not possible but deploy may proceed with reduced safety

Required: kubectl, velero CLI in PATH, KUBECONFIG pointing at target.

Usage:
  python3 bin/velero_pre_deploy_backup.py
  python3 bin/velero_pre_deploy_backup.py --git-sha abc1234 --backup-timeout 600
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

EXCLUDED_NAMESPACES = "kube-system,velero"


# ── reachability gates (testable via subprocess mocks) ──────────────────────


def cluster_reachable():
    """True if `kubectl cluster-info --request-timeout=10s` succeeds."""
    res = subprocess.run(
        ["kubectl", "cluster-info", "--request-timeout=10s"],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def velero_installed():
    """True if the velero deployment exists in the velero namespace."""
    res = subprocess.run(
        ["kubectl", "-n", "velero", "get", "deployment", "velero"],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


# ── backup operations ──────────────────────────────────────────────────────


def take_backup(name, timeout):
    """Run `velero backup create --wait`. Raises CalledProcessError on failure."""
    subprocess.run(
        [
            "velero",
            "backup",
            "create",
            name,
            "--include-namespaces",
            "*",
            "--exclude-namespaces",
            EXCLUDED_NAMESPACES,
            "--wait",
            "--request-timeout",
            f"{timeout}s",
        ],
        check=True,
    )


def get_backup_phase(name):
    """Return the .status.phase of a Velero backup, or 'Unknown' on error."""
    res = subprocess.run(
        [
            "kubectl",
            "-n",
            "velero",
            "get",
            "backup.velero.io",
            name,
            "-o",
            "jsonpath={.status.phase}",
        ],
        capture_output=True,
        text=True,
    )
    return res.stdout.strip() or "Unknown" if res.returncode == 0 else "Unknown"


def write_github_output(key, value):
    """Append a key=value line to $GITHUB_OUTPUT for downstream CI steps.

    Silent no-op if the env var isn't set (e.g., running locally).
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")
    except OSError:
        pass


# ── orchestration ──────────────────────────────────────────────────────────


def default_git_sha():
    """Return the short commit SHA, or 'unknown' if git isn't available."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except FileNotFoundError:
        pass
    return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--git-sha", default=os.environ.get("GIT_SHA") or default_git_sha()
    )
    parser.add_argument(
        "--backup-timeout",
        type=int,
        default=int(os.environ.get("BACKUP_TIMEOUT", "600")),
        help="Seconds to wait for the backup to reach Completed (default: 600).",
    )
    args = parser.parse_args(argv)

    backup_name = f"pre-deploy-{args.git_sha}-{int(time.time())}"

    # Reachability gates: warn loudly for first-deploy / post-destroy.
    # Exit 2 (not 0) so callers can distinguish "skipped" from "succeeded"
    # and surface a yellow annotation. Rollback safety is reduced in this
    # state — the caller decides whether to proceed.
    if not cluster_reachable():
        print(
            "⚠️  Cluster unreachable — no pre-deploy backup taken. "
            "Rollback will not be able to restore pre-deploy state.",
            file=sys.stderr,
        )
        print(
            "::warning ::Pre-deploy Velero backup SKIPPED (cluster unreachable). "
            "Rollback safety reduced."
        )
        return 2

    if not velero_installed():
        print(
            "⚠️  Velero not installed in target cluster — no pre-deploy backup taken.",
            file=sys.stderr,
        )
        print(
            "::warning ::Pre-deploy Velero backup SKIPPED (Velero absent). "
            "Install Velero to enable rollback safety."
        )
        return 2

    if shutil.which("velero") is None:
        print("❌ velero CLI not in PATH", file=sys.stderr)
        return 1

    print(f"📦 Creating Velero backup: {backup_name}")
    try:
        take_backup(backup_name, args.backup_timeout)
    except subprocess.CalledProcessError as e:
        print(f"❌ velero backup create failed (exit {e.returncode})", file=sys.stderr)
        return 1

    phase = get_backup_phase(backup_name)
    if phase != "Completed":
        print(f"❌ Backup phase={phase} (expected Completed)", file=sys.stderr)
        subprocess.run(["velero", "backup", "describe", backup_name, "--details"])
        return 1

    print(f"✅ Backup {backup_name} completed")
    write_github_output("BACKUP_NAME", backup_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
