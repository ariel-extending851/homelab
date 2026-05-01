"""End-to-end Velero backup + restore validation against a live cluster.

Marked `@pytest.mark.live` — skipped by default. Run via:

  python3 -m pytest bin/tests/test_velero_restore_live.py --run-live -v

  # or via the Makefile target which adds --run-live for you:
  make test-velero-restore

Required: KUBECONFIG pointing at a cluster with Velero installed and a
configured BackupStorageLocation (default `default` in the velero ns).

Tunables via env: BACKUP_TIMEOUT (s, default 300), RESTORE_TIMEOUT (s).
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest

pytestmark = pytest.mark.live

BACKUP_TIMEOUT = int(os.environ.get("BACKUP_TIMEOUT", "300"))
RESTORE_TIMEOUT = int(os.environ.get("RESTORE_TIMEOUT", "300"))


# ── helpers ────────────────────────────────────────────────────────────────


def _kubectl(*args, check=True, **kwargs):
    return subprocess.run(["kubectl", *args], check=check, text=True, **kwargs)


def _wait_for_phase(kind, name, timeout):
    """Poll a Velero CR's .status.phase until Completed or terminal failure.

    Returns the final phase. Raises AssertionError if the phase becomes
    Failed/PartiallyFailed or polling times out.
    """
    deadline = time.monotonic() + timeout
    last_phase = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "kubectl",
                "-n",
                "velero",
                "get",
                f"{kind}.velero.io",
                name,
                "-o",
                "jsonpath={.status.phase}",
            ],
            capture_output=True,
            text=True,
        )
        last_phase = result.stdout.strip() if result.returncode == 0 else ""
        if last_phase == "Completed":
            return last_phase
        if last_phase in ("Failed", "PartiallyFailed"):
            details = subprocess.run(
                [
                    "kubectl",
                    "-n",
                    "velero",
                    "get",
                    f"{kind}.velero.io",
                    name,
                    "-o",
                    "yaml",
                ],
                capture_output=True,
                text=True,
            ).stdout
            raise AssertionError(
                f"{kind} {name} terminated in phase={last_phase}\n{details}"
            )
        time.sleep(5)
    raise AssertionError(
        f"{kind} {name} timed out after {timeout}s (last phase={last_phase or 'pending'})"
    )


def _apply(manifest):
    """Apply a YAML manifest provided as a string via stdin."""
    subprocess.run(
        ["kubectl", "apply", "-f", "-"], input=manifest, text=True, check=True
    )


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def _velero_installed():
    """Module-level guard: skip the suite if Velero isn't installed."""
    res = subprocess.run(
        ["kubectl", "get", "deployment", "velero", "-n", "velero"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        pytest.skip("Velero deployment not found in 'velero' namespace")


@pytest.fixture()
def velero_test_resources(_velero_installed):
    """Create a unique namespace + marker ConfigMap; yield identifiers; clean up.

    Replaces the `trap cleanup EXIT` pattern from the original bash script
    with pytest's deterministic teardown.
    """
    suffix = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    ns = f"velero-restore-test-{suffix}"
    backup = f"restore-test-{suffix}-{int(time.time())}"
    restore = backup  # one fixture covers both lifecycles
    cm = "restore-marker"
    expected_data = f"velero-canary-{suffix}-{int(time.time())}"

    _kubectl("create", "namespace", ns)
    _kubectl(
        "create",
        "configmap",
        cm,
        "-n",
        ns,
        f"--from-literal=marker={expected_data}",
    )

    try:
        yield {
            "namespace": ns,
            "backup": backup,
            "restore": restore,
            "configmap": cm,
            "expected_data": expected_data,
        }
    finally:
        # Teardown — best-effort, don't mask test failure with cleanup errors.
        for args in (
            ["delete", "namespace", ns, "--ignore-not-found=true", "--wait=false"],
            [
                "delete",
                "-n",
                "velero",
                f"backup.velero.io",
                backup,
                "--ignore-not-found=true",
            ],
            [
                "delete",
                "-n",
                "velero",
                f"restore.velero.io",
                restore,
                "--ignore-not-found=true",
            ],
        ):
            subprocess.run(["kubectl", *args], capture_output=True, text=True)


# ── tests ──────────────────────────────────────────────────────────────────


def test_velero_installed(_velero_installed):
    """Sanity check: the Velero Deployment is present in the velero namespace."""
    # The fixture already asserted by skipping if absent; this test exists so
    # the suite has at least one always-discovered case for traceability.


def test_full_backup_restore_cycle(velero_test_resources):
    """Backup → delete → restore → verify ConfigMap data round-trips intact."""
    res = velero_test_resources
    ns = res["namespace"]
    backup = res["backup"]
    restore = res["restore"]
    cm = res["configmap"]
    expected = res["expected_data"]

    # Take backup.
    _apply(
        f"""apiVersion: velero.io/v1
kind: Backup
metadata:
  name: {backup}
  namespace: velero
spec:
  includedNamespaces:
    - {ns}
  ttl: 1h0m0s
  storageLocation: default
  snapshotMoveData: false
"""
    )
    _wait_for_phase("backup", backup, BACKUP_TIMEOUT)

    # Simulate disaster.
    _kubectl("delete", "namespace", ns, "--wait=true", "--timeout=60s")

    # Restore.
    _apply(
        f"""apiVersion: velero.io/v1
kind: Restore
metadata:
  name: {restore}
  namespace: velero
spec:
  backupName: {backup}
  includedNamespaces:
    - {ns}
"""
    )
    _wait_for_phase("restore", restore, RESTORE_TIMEOUT)

    # Verify the ConfigMap returned with its original payload.
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "configmap",
            cm,
            "-n",
            ns,
            "-o",
            "jsonpath={.data.marker}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        result.stdout.strip() == expected
    ), f"data mismatch: expected '{expected}', got '{result.stdout.strip()}'"
