"""k3d pre-deploy GitOps convergence test — catches manifest-level bugs.

Marked `@pytest.mark.live` only (no chaos/disruptive). It's hermetic-ish:
spins up a fresh k3d cluster on the runner, installs ArgoCD, applies the
GitOps tree, polls for convergence verdict, then tears the cluster down.

Why this exists: the existing `make validate-k8s-dry-run` (kind cluster)
runs `kubectl apply --dry-run=server` and destroys the cluster *before*
applying anything. Schema-valid manifests routinely fail at sync time
(broken kustomize, bad git refs, malformed CRDs, missing target paths).
This test closes that class of pre-merge failures.

Why we DON'T require Synced+Healthy: vanilla k3d in CI doesn't have the
operators the homelab depends on (Prometheus, Cilium, Falco, Velero,
Kyverno). Apps that need those operators stay `Missing` indefinitely —
that's not a manifest bug, just an integration-test gap. The pre-merge
gate here catches the bugs we *can* surface without a full operator
stack: ComparisonErrors on the root and child Applications.

Run via:
  make test-k3d-convergence

Skipped without `--run-live` AND a `k3d` binary on PATH (k3d is in
`.mise.toml`, so `mise install` is the one-time bootstrap).

What the test asserts (the real-bug contract):

  1. k3d cluster Ready on all nodes within 120s.
  2. argocd-server Deployment readyReplicas==replicas within 180s of apply.
  3. Root app-of-apps Application is *evaluated* (sync.status set) without
     a ComparisonError condition, within 300s of apply.
  4. No child Application has a ComparisonError condition (broken
     kustomize / bad ref / malformed CRD / sync-wave drift).

  SyncErrors (typically `no matches for kind PrometheusRule` from absent
  operator CRDs) are surfaced as advisory log lines — the workflow log
  records them but they do NOT fail the gate. See the unit tests in
  `test_k3d_convergence_unit.py` for the exact decision logic.
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
    dump_state_for_diagnostics,
    list_apps_with_comparison_errors,
    list_apps_with_sync_errors,
    list_unhealthy_applications,
    wait_for_argocd_server_ready,
    wait_for_cluster_ready,
    wait_for_root_app_evaluated,
)

pytestmark = pytest.mark.live

CLUSTER_NAME = os.environ.get("K3D_CLUSTER_NAME", "homelab-convergence")
ROOT_APP = os.environ.get("ROOT_APP_NAME", "homelab-apps-root")
CLUSTER_TIMEOUT = int(os.environ.get("K3D_CLUSTER_TIMEOUT", "120"))
ARGOCD_TIMEOUT = int(os.environ.get("ARGOCD_TIMEOUT", "180"))
SYNC_TIMEOUT = int(os.environ.get("SYNC_TIMEOUT", "300"))

# Where dump_state_for_diagnostics writes pre-teardown artifacts.
# The post-failure() upload-artifact step in ci-validation.yml reads
# from /tmp/k3d-failure-state by convention.
DIAGNOSTICS_DIR = os.environ.get("K3D_DIAGNOSTICS_DIR", "/tmp/k3d-failure-state")


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
    """End-to-end: cluster up → ArgoCD ready → root evaluated → no child errors.

    Single sequential test. Each step's failure mode requires the prior
    step to have succeeded — splitting them up would just make the
    diagnostic output noisier.

    The body is wrapped in try/finally so the diagnostic dump runs
    BEFORE the module-scoped k3d_cluster fixture's teardown deletes the
    cluster — otherwise the post-failure() artifact upload in CI gets
    empty files (which was happening on the first failed run).
    """
    try:
        # ── 1. cluster Ready ────────────────────────────────────────────
        wait_for_cluster_ready(timeout=CLUSTER_TIMEOUT)

        # ── 2. ArgoCD ready ─────────────────────────────────────────────
        apply_argocd()
        wait_for_argocd_server_ready(timeout=ARGOCD_TIMEOUT)

        # ── 3. root app reaches an evaluated state without ComparisonError
        apply_root_app()
        wait_for_root_app_evaluated(name=ROOT_APP, timeout=SYNC_TIMEOUT)

        # ── 4. no child Application has ComparisonError ─────────────────
        comparison_errors = list_apps_with_comparison_errors()
        assert not comparison_errors, (
            "child Applications have ComparisonError (manifest-level bugs):\n"
            + "\n".join(
                f"  - {app['namespace']}/{app['name']}: "
                f"{app['type']}: {app['message']}"
                for app in comparison_errors
            )
        )

        # ── advisory: log SyncErrors + unhealthy children ───────────────
        # These DON'T fail the gate — they're expected on a vanilla k3d
        # without the operator stack. Print so the workflow log shows
        # which apps would need attention if this were a real cluster.
        sync_errors = list_apps_with_sync_errors()
        if sync_errors:
            print(
                "\n[advisory] Applications with SyncError (expected on hermetic k3d):"
            )
            for app in sync_errors:
                print(f"  - {app['namespace']}/{app['name']}: {app['message'][:120]}")

        unhealthy = list_unhealthy_applications()
        if unhealthy:
            print("\n[advisory] Applications not yet Healthy (operator stack absent):")
            for app in unhealthy:
                print(
                    f"  - {app['namespace']}/{app['name']}: "
                    f"sync={app['sync']}, health={app['health']}"
                )
    finally:
        # ALWAYS dump state, success or failure — operators love
        # post-mortem artifacts and the dump is cheap. Critically: this
        # runs BEFORE k3d_cluster fixture teardown, so kubectl still
        # has a cluster to query.
        dump_state_for_diagnostics(DIAGNOSTICS_DIR)
