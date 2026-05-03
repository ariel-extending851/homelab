"""Tests for bin/smoke_test.py

Ports the six cases previously in bin/tests/smoke_tests.bats to pytest,
plus additional cases to exercise each check in isolation.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import smoke_test  # noqa: E402


# ── fake kubectl dispatcher ──────────────────────────────────────────────────


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _argocd_items(items):
    return json.dumps({"items": items})


def _healthy_app(name="app1"):
    return {
        "metadata": {"name": name},
        "status": {
            "sync": {"status": "Synced"},
            "health": {"status": "Healthy"},
        },
    }


def _build_kubectl_fake(overrides=None):
    """Return a side_effect callable emulating kubectl for a healthy cluster.

    overrides: dict keyed by command-signature prefix → CompletedProcess-ish
    """
    overrides = overrides or {}

    def _side_effect(cmd, *args, **kwargs):
        # cmd is e.g. ["kubectl", "--request-timeout=10s", "cluster-info"]
        key = " ".join(cmd[1:])
        for prefix, response in overrides.items():
            if key.startswith(prefix):
                return response

        # default healthy responses
        if "cluster-info" in key:
            return _proc(0, "Kubernetes control plane is running\n")
        if "get applications" in key and "-o json" in key:
            return _proc(0, _argocd_items([_healthy_app("app1")]))
        if "get pods -A --no-headers" in key:
            return _proc(0, "default   ok-pod   1/1   Running   0   1d\n")
        if "get namespace" in key:
            return _proc(0, "NAME    STATUS   AGE\n")
        if "get deployment argocd-repo-server" in key:
            return _proc(0, "1")
        if "get deployment" in key and "readyReplicas" in key:
            return _proc(0, "1")
        if "get deployment" in key and "spec.replicas" in key:
            return _proc(0, "1")
        if "get pvc" in key:
            return _proc(
                0, "media config-media Bound pvc-media 1Gi RWO local-path 2d\n"
            )
        if "get statefulset" in key:
            return _proc(0, "")
        return _proc(0, "")

    return _side_effect


# ── ported BATS: 1. happy path ───────────────────────────────────────────────


def test_smoke_exits_0_when_cluster_reachable_and_all_checks_pass(capsys):
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake()):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "All smoke tests passed" in out


# ── ported BATS: 2. cluster unreachable ──────────────────────────────────────


def test_smoke_exits_1_when_cluster_unreachable(capsys):
    overrides = {"--request-timeout=10s cluster-info": _proc(1, "", "error")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 1
    assert "unreachable" in capsys.readouterr().out


# ── ported BATS: 3. ArgoCD OutOfSync ─────────────────────────────────────────


def test_smoke_detects_out_of_sync_argocd_app(capsys):
    app = {
        "metadata": {"name": "my-app"},
        "status": {
            "sync": {"status": "OutOfSync"},
            "health": {"status": "Healthy"},
        },
    }
    overrides = {"get applications -n argocd -o json": _proc(0, _argocd_items([app]))}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 1
    assert "Not Synced" in capsys.readouterr().out


# ── ported BATS: 4. ArgoCD Degraded ──────────────────────────────────────────


def test_smoke_detects_degraded_argocd_app(capsys):
    app = {
        "metadata": {"name": "my-app"},
        "status": {
            "sync": {"status": "Synced"},
            "health": {"status": "Degraded"},
        },
    }
    overrides = {"get applications -n argocd -o json": _proc(0, _argocd_items([app]))}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 1
    assert "Not Healthy" in capsys.readouterr().out


# ── ported BATS: 5. CrashLoopBackOff pods ────────────────────────────────────


def test_smoke_detects_crashloop_pods(capsys):
    overrides = {
        "get pods -A --no-headers": _proc(
            0, "media   broken-pod   0/1   CrashLoopBackOff   5   10m\n"
        )
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 1
    assert "failure state" in capsys.readouterr().out


# ── ported BATS: 6. missing namespace ────────────────────────────────────────


def test_smoke_detects_missing_namespace(capsys):
    overrides = {"get namespace prometheus": _proc(1, "", "NotFound")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 1
    assert "missing" in capsys.readouterr().out


# ── ported BATS: 7. argocd-repo-server no replicas ───────────────────────────


def test_smoke_detects_argocd_repo_server_no_replicas(capsys):
    overrides = {"get deployment argocd-repo-server": _proc(0, "0")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 1
    assert "no ready replicas" in capsys.readouterr().out


# ── additional: exit 2 for minor issues ──────────────────────────────────────


def test_smoke_exits_2_when_only_a_couple_apps_fail(capsys):
    # Two specific apps fail; all other checks pass. Should exit 2.
    def side_effect(cmd, *args, **kwargs):
        key = " ".join(cmd[1:])
        if "get deployment grafana -n grafana" in key and "readyReplicas" in key:
            return _proc(0, "0")
            return _proc(0, "0")
        return _build_kubectl_fake()(cmd, *args, **kwargs)

    with patch("smoke_test.subprocess.run", side_effect=side_effect):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    assert rc == 2
    assert "Minor issues" in capsys.readouterr().out


def test_smoke_exits_1_when_three_or_more_apps_fail(capsys):
    def side_effect(cmd, *args, **kwargs):
        key = " ".join(cmd[1:])
        if "get deployment" in key and "readyReplicas" in key:
            # Everything except argocd-repo-server returns 0 replicas
            if "argocd-repo-server" not in key:
                return _proc(0, "0")
        return _build_kubectl_fake()(cmd, *args, **kwargs)

    with patch("smoke_test.subprocess.run", side_effect=side_effect):
        rc = smoke_test.SmokeTest(kubeconfig="/dev/null").run()
    # Many apps fail → apps_failed >= 3 → exit 1
    assert rc == 1


# ── individual check methods ─────────────────────────────────────────────────


def test_check_argocd_apps_reports_no_apps_when_items_empty(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get applications -n argocd -o json": _proc(0, _argocd_items([]))}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_apps()
    assert st.failed == 1
    assert "No ArgoCD applications found" in capsys.readouterr().out


def test_check_argocd_apps_handles_empty_stdout(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get applications -n argocd -o json": _proc(0, "")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_apps()
    assert st.failed == 1


def test_check_argocd_apps_handles_invalid_json(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get applications -n argocd -o json": _proc(0, "not-json")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_apps()
    assert st.failed == 1


def test_check_argocd_apps_handles_nonzero_returncode(capsys):
    """rbac denies list, CRD not installed, etc. — kubectl exits non-zero."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get applications -n argocd -o json": _proc(1, "", "forbidden")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_apps()
    assert st.failed == 1
    assert "No ArgoCD applications found" in capsys.readouterr().out


def test_check_pod_health_ignores_running_pods(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get pods -A --no-headers": _proc(0, "default  ok  1/1  Running  0  1d\n")
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_pod_health()
    assert st.failed == 0
    assert "No pods in failure state" in capsys.readouterr().out


def test_check_pvcs_detects_unbound(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get pvc -A --no-headers": _proc(
            0, "media bad-pvc Pending <unset> <unset> <unset> local-path 5m\n"
        )
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_pvcs()
    assert st.failed == 1
    out = capsys.readouterr().out
    assert "not Bound" in out
    assert "bad-pvc" in out


def test_check_pvcs_reports_total_when_all_bound(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get pvc -A --no-headers": _proc(
            0,
            "media cfg-1 Bound pvc-1 1Gi RWO local-path 2d\n"
            "media cfg-2 Bound pvc-2 1Gi RWO local-path 2d\n",
        )
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_pvcs()
    assert st.failed == 0
    assert "All 2 non-on-demand PVCs are Bound" in capsys.readouterr().out


def test_check_statefulsets_detects_replica_mismatch(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get statefulset -A --no-headers": _proc(0, "ns sts1 2/3 1d\n")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_statefulsets()
    assert st.failed == 1
    out = capsys.readouterr().out
    assert "mismatch" in out
    assert "sts1" in out
    assert "2/3" in out


def test_check_statefulsets_handles_empty_cluster(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get statefulset -A --no-headers": _proc(0, "")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_statefulsets()
    assert st.failed == 0
    assert "No StatefulSets to validate" in capsys.readouterr().out


def test_check_observability_detects_prometheus_down(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")

    def side_effect(cmd, *args, **kwargs):
        key = " ".join(cmd[1:])
        if "get deployment prometheus" in key and "readyReplicas" in key:
            return _proc(0, "0")
        return _build_kubectl_fake()(cmd, *args, **kwargs)

    with patch("smoke_test.subprocess.run", side_effect=side_effect):
        st.check_observability()
    out = capsys.readouterr().out
    assert "Prometheus: no ready replicas" in out


def test_check_observability_detects_loki_down(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")

    def side_effect(cmd, *args, **kwargs):
        key = " ".join(cmd[1:])
        if "get deployment loki" in key and "readyReplicas" in key:
            return _proc(0, "0")
        return _build_kubectl_fake()(cmd, *args, **kwargs)

    with patch("smoke_test.subprocess.run", side_effect=side_effect):
        st.check_observability()
    assert "Loki: no ready replicas" in capsys.readouterr().out


def test_deployment_int_falls_back_to_zero_on_non_numeric(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get deployment x": _proc(0, "garbage")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        n = st._deployment_int("x", "y", "{.status.readyReplicas}")
    assert n == 0


def test_argocd_repo_server_handles_empty_stdout(capsys):
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get deployment argocd-repo-server": _proc(0, "")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_repo_server()
    assert st.failed == 1


# ── main entry point ────────────────────────────────────────────────────────


def test_main_uses_env_kubeconfig_and_argocd_namespace(monkeypatch):
    monkeypatch.setenv("KUBECONFIG", "/path/to/kc")
    monkeypatch.setenv("ARGOCD_NAMESPACE", "custom-argo")
    captured = {}

    class _StubSmoke:
        def __init__(self, kubeconfig, argocd_ns):
            captured["kc"] = kubeconfig
            captured["ns"] = argocd_ns

        def run(self):
            return 0

    with patch("smoke_test.SmokeTest", _StubSmoke):
        rc = smoke_test.main()
    assert rc == 0
    assert captured["kc"] == "/path/to/kc"
    assert captured["ns"] == "custom-argo"


def test_main_default_kubeconfig(monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.delenv("ARGOCD_NAMESPACE", raising=False)
    captured = {}

    class _StubSmoke:
        def __init__(self, kubeconfig, argocd_ns):
            captured["kc"] = kubeconfig
            captured["ns"] = argocd_ns

        def run(self):
            return 0

    with patch("smoke_test.SmokeTest", _StubSmoke):
        smoke_test.main()
    assert captured["kc"] == "/tmp/k3s-homelab-kubeconfig.yaml"
    assert captured["ns"] == "argocd"


# ── additional branch-coverage tests ────────────────────────────────────────


def test_argocd_repo_server_handles_non_numeric_stdout(capsys):
    """Line 167-168 branch: ValueError fallback when readyReplicas is non-numeric."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get deployment argocd-repo-server": _proc(0, "NaN")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_repo_server()
    assert st.failed == 1
    assert "no ready replicas" in capsys.readouterr().out


def test_check_statefulsets_reports_total_when_all_match(capsys):
    """'All X StatefulSets match desired replicas' when ready == desired for all rows."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {"get statefulset -A --no-headers": _proc(0, "ns sts-ok 1/1 1d\n")}
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_statefulsets()
    assert st.failed == 0
    assert "All 1 StatefulSets match desired replicas" in capsys.readouterr().out


def test_check_statefulsets_skips_short_lines(capsys):
    """Lines with fewer than 3 cols, or no '/' in the READY field, are discarded."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get statefulset -A --no-headers": _proc(0, "short\nns name notreadyfmt 1d\n")
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_statefulsets()
    assert st.failed == 0


# ── Failure-path tests (Tier 3 — realistic failure scenarios) ───────────────


def test_check_argocd_apps_flags_outofsync_app(capsys):
    """A single OutOfSync app must register as a failure."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    out_of_sync = {
        "metadata": {"name": "drifted-app"},
        "status": {
            "sync": {"status": "OutOfSync"},
            "health": {"status": "Healthy"},
        },
    }
    overrides = {
        "get applications -n argocd -o json": _proc(0, _argocd_items([out_of_sync])),
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_apps()
    out = capsys.readouterr().out
    assert "Not Synced" in out
    assert "drifted-app" in out
    assert st.failed >= 1


def test_check_argocd_apps_flags_degraded_app(capsys):
    """Healthy-sync but Degraded health must still register as a failure."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    degraded = {
        "metadata": {"name": "broken-app"},
        "status": {
            "sync": {"status": "Synced"},
            "health": {"status": "Degraded"},
        },
    }
    overrides = {
        "get applications -n argocd -o json": _proc(0, _argocd_items([degraded])),
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_apps()
    out = capsys.readouterr().out
    assert "Not Healthy" in out
    assert "broken-app" in out


def test_check_pod_health_detects_imagepullbackoff(capsys):
    """ImagePullBackOff (common after CI image tag drift) must be flagged."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get pods -A --no-headers": _proc(
            0,
            "argocd  argocd-image-updater-broken-9dd  0/1  ImagePullBackOff  3  30m\n",
        )
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_pod_health()
    out = capsys.readouterr().out
    assert "failure state" in out
    assert "ImagePullBackOff" in out


def test_check_pod_health_detects_crashloopbackoff(capsys):
    """CrashLoopBackOff (most common failure mode) must be flagged."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get pods -A --no-headers": _proc(
            0,
            "loki  loki-0  0/1  CrashLoopBackOff  12  1h\n",
        )
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_pod_health()
    assert "CrashLoopBackOff" in capsys.readouterr().out


def test_check_argocd_repo_server_zero_ready_replicas_fails(capsys):
    """SOPS CMP sidecar broken → repo-server 0/1 ready → FAIL with diagnostic hint."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "get deployment argocd-repo-server": _proc(0, "0"),
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        st.check_argocd_repo_server()
    out = capsys.readouterr().out
    assert "no ready replicas" in out
    assert "SOPS" in out or "CMP" in out


def test_cluster_unreachable_short_circuits_remaining_checks(capsys):
    """If kubectl can't reach the API server, check_cluster_reachable returns False."""
    st = smoke_test.SmokeTest(kubeconfig="/dev/null")
    overrides = {
        "--request-timeout=10s cluster-info": _proc(1, "", "connection refused")
    }
    with patch("smoke_test.subprocess.run", side_effect=_build_kubectl_fake(overrides)):
        reachable = st.check_cluster_reachable()
    assert reachable is False
    out = capsys.readouterr().out
    assert "unreachable" in out
