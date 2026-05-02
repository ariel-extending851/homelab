"""Unit tests for bin/k3d_convergence.py helpers — pure-function coverage.

Distinct from `test_k3d_gitops_convergence.py` (which is the live, --run-live
end-to-end test). This file uses monkeypatched `_kubectl_json` to validate
the decision logic the CI gate relies on: which Application states represent
real bugs (ComparisonError) vs. acceptable-on-k3d limitations (SyncError due
to absent operator CRDs).

These tests are why we can run a relaxed gate on a vanilla k3d cluster
without losing the bugs the gate exists to catch.
"""

from __future__ import annotations

import pytest

from bin import k3d_convergence as kc


# ── helpers ──────────────────────────────────────────────────────────────


def _root_app(
    sync_status: str = "Synced",
    health_status: str = "Healthy",
    conditions: list | None = None,
) -> dict:
    """Build a minimal Application JSON shape for monkeypatching kubectl get."""
    return {
        "metadata": {"name": "homelab-apps-root", "namespace": "argocd"},
        "spec": {"source": {"targetRevision": "abc123"}},
        "status": {
            "sync": {"status": sync_status, "revision": "abc123"},
            "health": {"status": health_status},
            "conditions": conditions or [],
        },
    }


def _child_app(
    name: str,
    namespace: str = "argocd",
    sync_status: str = "Synced",
    health_status: str = "Healthy",
    conditions: list | None = None,
) -> dict:
    return {
        "metadata": {"name": name, "namespace": namespace},
        "status": {
            "sync": {"status": sync_status},
            "health": {"status": health_status},
            "conditions": conditions or [],
        },
    }


# ── wait_for_root_app_evaluated ─────────────────────────────────────────


def test_root_evaluated_passes_when_synced_no_errors(monkeypatch):
    """sync.status=Synced + no error conditions → returns immediately."""
    monkeypatch.setattr(
        kc, "_kubectl_json", lambda *args: _root_app(sync_status="Synced")
    )
    # Should not raise, should return promptly (no real timeout).
    kc.wait_for_root_app_evaluated(name="homelab-apps-root", timeout=5)


def test_root_evaluated_passes_when_outofsync_no_comparison_error(monkeypatch):
    """OutOfSync is acceptable — proves comparison happened. Real bug check
    is the absence of ComparisonError, not the sync verdict itself."""
    monkeypatch.setattr(
        kc,
        "_kubectl_json",
        lambda *args: _root_app(sync_status="OutOfSync", health_status="Missing"),
    )
    kc.wait_for_root_app_evaluated(name="homelab-apps-root", timeout=5)


def test_root_evaluated_fails_on_comparison_error(monkeypatch):
    """ComparisonError = real bug (broken kustomize, bad ref, missing path).
    The gate must catch it loudly."""
    cond = {
        "type": "ComparisonError",
        "message": "rpc error: failed to load target state: kustomize build failed",
    }
    monkeypatch.setattr(
        kc,
        "_kubectl_json",
        lambda *args: _root_app(sync_status="Unknown", conditions=[cond]),
    )
    with pytest.raises(AssertionError, match="ComparisonError"):
        kc.wait_for_root_app_evaluated(name="homelab-apps-root", timeout=5)


def test_root_evaluated_times_out_when_sync_status_empty(monkeypatch):
    """Empty sync.status means ArgoCD never even started comparison —
    likely the auto-sync controller is wedged. Surface as timeout, not
    silent pass."""
    monkeypatch.setattr(kc, "_kubectl_json", lambda *args: _root_app(sync_status=""))
    # Tight timeout so the test runs fast.
    with pytest.raises(AssertionError, match="never reached an evaluated state"):
        kc.wait_for_root_app_evaluated(name="homelab-apps-root", timeout=1)


# ── list_apps_with_comparison_errors ────────────────────────────────────


def test_comparison_errors_returns_only_comparison_errors(monkeypatch):
    """SyncError must NOT show up here — it's handled separately."""
    payload = {
        "items": [
            _child_app(
                "broken-kustomize",
                conditions=[
                    {"type": "ComparisonError", "message": "kustomize build failed"}
                ],
            ),
            _child_app(
                "missing-crd",
                conditions=[
                    {
                        "type": "SyncError",
                        "message": "no matches for kind PrometheusRule",
                    }
                ],
            ),
            _child_app("happy", conditions=[]),
        ]
    }
    monkeypatch.setattr(kc, "_kubectl_json", lambda *args: payload)
    out = kc.list_apps_with_comparison_errors()
    assert len(out) == 1
    assert out[0]["name"] == "broken-kustomize"
    assert out[0]["type"] == "ComparisonError"


def test_comparison_errors_empty_when_only_sync_errors(monkeypatch):
    """A cluster with only SyncErrors (the k3d-without-operators case) must
    return an empty list — otherwise the gate falsely fails."""
    payload = {
        "items": [
            _child_app(
                "needs-prom-operator",
                conditions=[
                    {
                        "type": "SyncError",
                        "message": "no matches for kind PrometheusRule",
                    }
                ],
            ),
            _child_app(
                "needs-cilium",
                conditions=[
                    {
                        "type": "SyncError",
                        "message": "no matches for kind CiliumNetworkPolicy",
                    }
                ],
            ),
        ]
    }
    monkeypatch.setattr(kc, "_kubectl_json", lambda *args: payload)
    assert kc.list_apps_with_comparison_errors() == []


# ── list_apps_with_sync_errors ──────────────────────────────────────────


def test_sync_errors_collects_for_advisory_log(monkeypatch):
    """SyncErrors are advisory but worth surfacing in logs so the operator
    knows which apps would fail without the operator stack."""
    payload = {
        "items": [
            _child_app(
                "needs-prom-operator",
                conditions=[
                    {
                        "type": "SyncError",
                        "message": "no matches for kind PrometheusRule",
                    }
                ],
            ),
            _child_app(
                "broken",
                conditions=[
                    {"type": "ComparisonError", "message": "kustomize build failed"}
                ],
            ),
        ]
    }
    monkeypatch.setattr(kc, "_kubectl_json", lambda *args: payload)
    out = kc.list_apps_with_sync_errors()
    assert len(out) == 1
    assert out[0]["name"] == "needs-prom-operator"
    assert out[0]["type"] == "SyncError"


def test_sync_errors_empty_when_clean(monkeypatch):
    payload = {
        "items": [
            _child_app("a", conditions=[]),
            _child_app("b", conditions=[]),
        ]
    }
    monkeypatch.setattr(kc, "_kubectl_json", lambda *args: payload)
    assert kc.list_apps_with_sync_errors() == []


# ── dump_state_for_diagnostics ──────────────────────────────────────────


def test_dump_state_writes_files(tmp_path, monkeypatch):
    """The diagnostic dump must run from inside the test — workflow-side
    dump runs after fixture teardown, when the cluster is already gone."""
    captured: list = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        # Pretend kubectl produced output.
        from bin.rollback import _FakeProc

        return _FakeProc(returncode=0, stdout="apiVersion: v1\nitems: []\n")

    monkeypatch.setattr(kc.subprocess, "run", fake_run)
    out_dir = tmp_path / "diag"

    kc.dump_state_for_diagnostics(out_dir)

    assert (out_dir / "argocd-apps.yaml").exists()
    assert (out_dir / "all-pods.txt").exists()
    # Both kubectl calls were made.
    assert any("applications.argoproj.io" in str(c) for c in captured)
    assert any("pods" in str(c) for c in captured)


def test_dump_state_swallows_errors(tmp_path, monkeypatch):
    """Diagnostic dump must NEVER raise — it runs in finally: blocks
    where re-raising would mask the real assertion failure."""

    def fake_run(cmd, **kw):
        raise RuntimeError("kubectl exploded")

    monkeypatch.setattr(kc.subprocess, "run", fake_run)
    # Should not raise.
    kc.dump_state_for_diagnostics(tmp_path / "diag")
