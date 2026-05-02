"""Shared kubectl + polling helpers for live tests.

Extracted from `test_velero_restore_live.py` so the chaos and convergence
tests can reuse the same primitives instead of cloning subprocess logic.

Leading underscore in the filename keeps this file inside the `*/tests/*`
omit glob in `pyproject.toml`, so it is not counted against the coverage
floor — the helpers are exercised through the live tests that use them.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Callable


def _kubectl(
    *args: str, check: bool = True, **kwargs: Any
) -> subprocess.CompletedProcess:
    """Run `kubectl <args>` synchronously.

    Mirrors the historical signature in test_velero_restore_live.py so that
    refactor preserves call sites verbatim.
    """
    return subprocess.run(["kubectl", *args], check=check, text=True, **kwargs)


def _apply(manifest: str) -> None:
    """Apply a YAML manifest provided as an in-memory string."""
    subprocess.run(
        ["kubectl", "apply", "-f", "-"], input=manifest, text=True, check=True
    )


def _wait_for_phase(
    kind: str, name: str, timeout: int, namespace: str = "velero"
) -> str:
    """Poll a Velero CR's `.status.phase` until terminal.

    Returns the final phase. Raises AssertionError on Failed/PartiallyFailed
    or polling timeout. Default namespace is `velero` to keep the original
    Velero call sites short.
    """
    deadline = time.monotonic() + timeout
    last_phase = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "kubectl",
                "-n",
                namespace,
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
                    namespace,
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


def wait_for(
    predicate: Callable[[], bool], timeout: float, interval: float = 2.0
) -> None:
    """Poll `predicate` until it returns truthy or timeout elapses.

    Raises AssertionError on timeout. Use for one-off readiness checks where
    a kubectl wait command isn't expressive enough (e.g. parsing JSON across
    multiple resources, or Prometheus query results).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"predicate did not become truthy within {timeout}s")


def app_health(name: str, namespace: str = "argocd") -> tuple[str, str]:
    """Return ArgoCD Application's (sync_status, health_status) pair.

    Empty strings if the Application doesn't exist or status is missing.
    """
    res = subprocess.run(
        [
            "kubectl",
            "-n",
            namespace,
            "get",
            "applications.argoproj.io",
            name,
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return "", ""
    try:
        obj = json.loads(res.stdout)
    except json.JSONDecodeError:
        return "", ""
    status = obj.get("status", {})
    return (
        status.get("sync", {}).get("status", ""),
        status.get("health", {}).get("status", ""),
    )
