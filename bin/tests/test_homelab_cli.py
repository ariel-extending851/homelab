"""Tests for bin/homelab.py — verifies sub-command dispatch + output formatting."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import homelab  # noqa: E402


# ── render_argocd_diagnose (pure) ───────────────────────────────────────────


def _argo_payload(
    name="root",
    sync="Synced",
    health="Healthy",
    conditions=None,
    op_phase=None,
    op_msg=None,
):
    return json.dumps(
        {
            "metadata": {"name": name},
            "status": {
                "sync": {"status": sync},
                "health": {"status": health},
                "conditions": conditions,
                "operationState": (
                    {"phase": op_phase, "message": op_msg}
                    if (op_phase or op_msg)
                    else None
                ),
            },
        }
    )


def test_render_synced_healthy_no_conditions_returns_zero():
    buf = io.StringIO()
    rc = homelab.render_argocd_diagnose(_argo_payload(), buf)
    assert rc == 0
    out = buf.getvalue()
    assert "App: root" in out
    assert "Sync:   Synced" in out
    assert "Health: Healthy" in out
    assert "Conditions: (none)" in out


def test_render_with_conditions_returns_one():
    payload = _argo_payload(
        sync="OutOfSync",
        health="Degraded",
        conditions=[{"type": "ComparisonError", "message": "manifest invalid"}],
    )
    buf = io.StringIO()
    rc = homelab.render_argocd_diagnose(payload, buf)
    assert rc == 1
    out = buf.getvalue()
    assert "[ComparisonError] manifest invalid" in out


def test_render_includes_last_operation_when_present():
    payload = _argo_payload(op_phase="Failed", op_msg="apply timed out")
    buf = io.StringIO()
    homelab.render_argocd_diagnose(payload, buf)
    assert "Last operation: Failed — apply timed out" in buf.getvalue()


def test_render_handles_invalid_json(capsys):
    rc = homelab.render_argocd_diagnose("{not json", io.StringIO())
    assert rc == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_render_handles_empty_input(capsys):
    buf = io.StringIO()
    rc = homelab.render_argocd_diagnose("", buf)
    # empty string → empty dict → unknown values, no conditions = exits 1
    # (sync and health not "Synced/Healthy")
    assert rc == 1
    assert "App: <unknown>" in buf.getvalue()


# ── argocd diagnose CLI dispatch ─────────────────────────────────────────────


def test_argocd_diagnose_kubectl_failure_returns_two(capsys):
    fake = MagicMock(returncode=1, stdout="", stderr="not found")
    with patch.object(homelab, "_kubectl", return_value=fake):
        rc = homelab.main(["argocd", "diagnose", "missing-app"])
    assert rc == 2
    assert "kubectl failed: not found" in capsys.readouterr().err


def test_argocd_diagnose_dispatches_with_namespace_override():
    fake = MagicMock(returncode=0, stdout=_argo_payload(), stderr="")
    captured = {}

    def fake_kubectl(argv, kubeconfig=None, timeout=None):
        captured["argv"] = argv
        captured["kubeconfig"] = kubeconfig
        return fake

    with patch.object(homelab, "_kubectl", side_effect=fake_kubectl):
        rc = homelab.main(
            [
                "argocd",
                "diagnose",
                "grafana",
                "--namespace",
                "argo-prod",
                "--kubeconfig",
                "/tmp/kc",
            ]
        )
    assert rc == 0
    assert captured["argv"] == [
        "get",
        "application",
        "grafana",
        "-n",
        "argo-prod",
        "-o",
        "json",
    ]
    assert captured["kubeconfig"] == "/tmp/kc"


# ── tf drift CLI dispatch ────────────────────────────────────────────────────


class _StubDrift:
    """Stub that sets a fixed tf.drift check result."""

    def __init__(self, args, status="pass", message="no drift"):
        self.args = args
        self.checks = [{"name": "tf.drift", "status": status, "message": message}]

    def check_terraform(self):
        return None

    def render(self, out):
        out.write(f"tf.drift: {self.checks[0]['status']}\n")


def test_tf_drift_summary_pass_returns_zero(capsys):
    with patch.object(
        homelab.drift, "Drift", lambda a: _StubDrift(a, "pass", "no drift")
    ):
        rc = homelab.main(["tf", "drift", "--summary"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "✓ tf.drift: pass — no drift" in out


def test_tf_drift_summary_fail_returns_one(capsys):
    with patch.object(
        homelab.drift, "Drift", lambda a: _StubDrift(a, "fail", "5 resource(s) changed")
    ):
        rc = homelab.main(["tf", "drift", "--summary"])
    assert rc == 1
    assert "✗ tf.drift: fail" in capsys.readouterr().out


def test_tf_drift_full_report_uses_render(capsys):
    with patch.object(
        homelab.drift, "Drift", lambda a: _StubDrift(a, "pass", "no drift")
    ):
        rc = homelab.main(["tf", "drift"])
    assert rc == 0
    assert "tf.drift: pass" in capsys.readouterr().out


def test_tf_drift_skipped_check_returns_zero():
    with patch.object(
        homelab.drift, "Drift", lambda a: _StubDrift(a, "skip", "no terraform dir")
    ):
        rc = homelab.main(["tf", "drift", "--summary"])
    assert rc == 0


# ── parser ──────────────────────────────────────────────────────────────────


def test_no_subcommand_exits_two(capsys):
    with pytest.raises(SystemExit) as exc:
        homelab.main([])
    assert exc.value.code == 2


def test_argocd_without_command_exits_two():
    with pytest.raises(SystemExit) as exc:
        homelab.main(["argocd"])
    assert exc.value.code == 2


# ── argocd list ──────────────────────────────────────────────────────────────


def _argo_list_payload(apps):
    items = []
    for name, sync, health in apps:
        items.append(
            {
                "metadata": {"name": name},
                "status": {
                    "sync": {"status": sync},
                    "health": {"status": health},
                },
            }
        )
    return json.dumps({"items": items})


def test_argocd_list_all_synced_returns_zero():
    payload = _argo_list_payload(
        [
            ("root", "Synced", "Healthy"),
            ("grafana", "Synced", "Healthy"),
        ]
    )
    buf = io.StringIO()
    rc = homelab.render_argocd_list(payload, buf)
    assert rc == 0
    out = buf.getvalue()
    assert "root" in out and "grafana" in out
    assert "2 apps, 0 not Synced" in out


def test_argocd_list_some_drift_returns_one():
    payload = _argo_list_payload(
        [
            ("root", "Synced", "Healthy"),
            ("grafana", "OutOfSync", "Degraded"),
        ]
    )
    buf = io.StringIO()
    rc = homelab.render_argocd_list(payload, buf)
    assert rc == 1
    assert "1 not Synced" in buf.getvalue()


def test_argocd_list_empty_returns_one():
    buf = io.StringIO()
    rc = homelab.render_argocd_list('{"items": []}', buf)
    assert rc == 1
    assert "No ArgoCD applications" in buf.getvalue()


# ── k3s status ───────────────────────────────────────────────────────────────


def test_k3s_status_all_ready_returns_zero():
    stdout = (
        "node1 Ready control-plane,master 1d v1.28.5 10.0.0.1\n"
        "node2 Ready <none> 1d v1.28.5 10.0.0.2\n"
    )
    buf = io.StringIO()
    rc = homelab.render_k3s_status(stdout, buf)
    assert rc == 0
    out = buf.getvalue()
    assert "node1" in out and "node2" in out
    assert "2 nodes, 0 not Ready" in out


def test_k3s_status_node_not_ready_returns_one():
    stdout = "node1 NotReady <none> 1d v1.28.5 10.0.0.1\n"
    buf = io.StringIO()
    rc = homelab.render_k3s_status(stdout, buf)
    assert rc == 1
    assert "1 not Ready" in buf.getvalue()


def test_k3s_status_no_nodes_returns_one():
    buf = io.StringIO()
    rc = homelab.render_k3s_status("", buf)
    assert rc == 1


# ── ci replay ────────────────────────────────────────────────────────────────


def test_ci_replay_unknown_step_returns_two(capsys):
    rc = homelab.main(["ci", "replay", "bogus-target"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Unknown step" in err
    assert "smoke-test" in err  # lists valid steps


def test_ci_replay_invokes_make():
    captured = {}

    def fake_call(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return 0

    with patch("subprocess.call", side_effect=fake_call):
        rc = homelab.main(["ci", "replay", "smoke-test"])
    assert rc == 0
    assert captured["cmd"] == ["make", "smoke-test"]


def test_ci_replay_propagates_make_exit_code():
    with patch("subprocess.call", return_value=42):
        rc = homelab.main(["ci", "replay", "smoke-test"])
    assert rc == 42


# ── tf cost ──────────────────────────────────────────────────────────────────


def test_tf_cost_invokes_make_show_costs():
    captured = {}

    def fake_call(cmd, cwd=None):
        captured["cmd"] = cmd
        return 0

    with patch("subprocess.call", side_effect=fake_call):
        rc = homelab.main(["tf", "cost"])
    assert rc == 0
    assert captured["cmd"] == ["make", "show-costs"]
