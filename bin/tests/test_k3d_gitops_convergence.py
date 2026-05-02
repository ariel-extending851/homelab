"""k3d pre-deploy GitOps convergence test — catches sync-wave drift.

Marked `@pytest.mark.live` only (no chaos/disruptive). It's hermetic-ish:
spins up a fresh k3d cluster on the runner, installs ArgoCD, applies the
GitOps tree, polls for convergence, then tears the cluster down.

Why this exists: the existing `make validate-k8s-dry-run` (kind cluster)
runs `kubectl apply --dry-run=server` and destroys the cluster *before*
applying anything. Schema-valid manifests routinely fail to converge
(sync waves, CRD ordering, missing secret refs). This test closes that
class of pre-merge failures.

Run via:
  make test-k3d-convergence

Skipped without `--run-live` AND a `k3d` binary on PATH (k3d is in
`.mise.toml`, so `mise install` is the one-time bootstrap).

What the test asserts:

  1. k3d cluster Ready on all nodes within 120s.
  2. argocd-server Deployment readyReplicas==replicas within 180s of apply.
  3. Root app-of-apps Application reaches Synced AND Healthy within 600s.
  4. Every child Application is Synced+Healthy. On red, the test prints
     the full status conditions of each failing Application (the payoff).
  5. No Application has a ComparisonError or SyncError condition.
"""

from __future__ import annotations

import os
import shutil

import pytest

from bin.k3d_convergence import (
    apply_argocd,
    apply_root_app,
    create_k3d_cluster,
    delete_k3d_cluster,
    list_unhealthy_applications,
    list_applications_with_errors,
    wait_for_argocd_server_ready,
    wait_for_cluster_ready,
    wait_for_root_app_synced_healthy,
)

pytestmark = pytest.mark.live

CLUSTER_NAME = os.environ.get("K3D_CLUSTER_NAME", "homelab-convergence")
ROOT_APP = os.environ.get("ROOT_APP_NAME", "homelab-apps-root")
CLUSTER_TIMEOUT = int(os.environ.get("K3D_CLUSTER_TIMEOUT", "120"))
ARGOCD_TIMEOUT = int(os.environ.get("ARGOCD_TIMEOUT", "180"))
SYNC_TIMEOUT = int(os.environ.get("SYNC_TIMEOUT", "600"))


def _require_k3d() -> None:
    if not shutil.which("k3d"):
        pytest.skip("k3d binary not found; run `mise install` to fetch it")


@pytest.fixture(scope="module")
def k3d_cluster():
    """Create a clean k3d cluster scoped to this test run.

    Always tears down — even on assertion failure — so the runner stays
    clean for subsequent jobs.
    """
    _require_k3d()
    create_k3d_cluster(CLUSTER_NAME)
    try:
        yield CLUSTER_NAME
    finally:
        delete_k3d_cluster(CLUSTER_NAME)


def test_full_convergence(k3d_cluster: str) -> None:
    """End-to-end: cluster up → ArgoCD ready → all Apps Synced+Healthy.

    Single sequential test. Each step's failure mode requires the prior
    step to have succeeded — splitting them up would just make the
    diagnostic output noisier.
    """
    # ── 1. cluster Ready ────────────────────────────────────────────────
    wait_for_cluster_ready(timeout=CLUSTER_TIMEOUT)

    # ── 2. ArgoCD ready ─────────────────────────────────────────────────
    apply_argocd()
    wait_for_argocd_server_ready(timeout=ARGOCD_TIMEOUT)

    # ── 3. root app-of-apps Synced + Healthy ────────────────────────────
    apply_root_app()
    wait_for_root_app_synced_healthy(name=ROOT_APP, timeout=SYNC_TIMEOUT)

    # ── 4. every child Application is Healthy ───────────────────────────
    unhealthy = list_unhealthy_applications()
    assert not unhealthy, "child Applications failed to converge:\n" + "\n".join(
        f"  - {app['namespace']}/{app['name']}: "
        f"sync={app['sync']}, health={app['health']}, "
        f"message={app.get('message', '')}"
        for app in unhealthy
    )

    # ── 5. no ComparisonError / SyncError conditions ────────────────────
    errored = list_applications_with_errors()
    assert not errored, "Applications with sync/comparison errors:\n" + "\n".join(
        f"  - {app['namespace']}/{app['name']}: " f"{app['type']}: {app['message']}"
        for app in errored
    )
