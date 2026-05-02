"""Tests for bin/homelab.py — the canonical CLI entry point.

Covers parser registration, argv passthrough, exit code propagation, and
that each new subcommand handler delegates to the right backing module.
Existing argocd/tf/k3s/ci subcommands are not re-tested here; they have
their own coverage via the rendered output paths.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import homelab  # noqa: E402


# ── parser registration ─────────────────────────────────────────────────────


def test_build_parser_registers_all_top_level_groups():
    parser = homelab.build_parser()
    # Walk the subparsers action to enumerate registered group names.
    sub_action = next(
        a
        for a in parser._actions
        if isinstance(a, type(parser._subparsers._group_actions[0]))
    )
    expected = {
        "argocd",
        "tf",
        "k3s",
        "ci",
        "deploy",
        "preflight",
        "smoke",
        "rollback",
        "backup",
        "drift",
    }
    assert expected.issubset(set(sub_action.choices))


def test_build_parser_backup_has_pre_and_verify():
    parser = homelab.build_parser()
    args = parser.parse_args(["backup", "pre"])
    assert args.func is homelab.cmd_backup_pre
    args = parser.parse_args(["backup", "verify"])
    assert args.func is homelab.cmd_backup_verify


def test_top_level_help_does_not_raise(capsys):
    with pytest.raises(SystemExit) as exc:
        homelab.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "homelab" in out
    for group in ("deploy", "preflight", "smoke", "rollback", "backup", "drift"):
        assert group in out


@pytest.mark.parametrize(
    "group_argv",
    [
        ["deploy", "--help"],
        ["preflight", "--help"],
        ["rollback", "--help"],
        ["backup", "--help"],
        ["backup", "pre", "--help"],
        ["drift", "--help"],
    ],
)
def test_subcommand_help_exits_zero(capsys, group_argv):
    with pytest.raises(SystemExit) as exc:
        homelab.main(group_argv)
    assert exc.value.code == 0
    assert capsys.readouterr().out  # non-empty


def test_unknown_subcommand_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        homelab.main(["nonsense-subcommand"])
    assert exc.value.code != 0


# ── delegation: each new handler forwards argv to the backing module ────────


class _Recorder:
    """Capture (argv) calls to a fake module main() and return a chosen rc."""

    def __init__(self, rc=0):
        self.rc = rc
        self.calls = []

    def main(self, argv=None):
        self.calls.append(argv)
        return self.rc


def test_cmd_deploy_delegates_with_passthrough(monkeypatch):
    rec = _Recorder(rc=7)
    monkeypatch.setitem(sys.modules, "deploy_aws_homelab", rec)
    rc = homelab.main(["deploy", "--destroy"])
    assert rc == 7
    assert rec.calls == [["--destroy"]]


def test_subcommand_help_is_intercepted_not_forwarded(monkeypatch, capsys):
    """`homelab preflight --help` shows the wrapper help and exits 0;
    it does NOT delegate to bin/preflight.py. To get the underlying tool's
    help, users pass `--` first (or invoke the script directly)."""
    rec = _Recorder(rc=99)
    monkeypatch.setitem(sys.modules, "preflight", rec)
    with pytest.raises(SystemExit) as exc:
        homelab.main(["preflight", "--help"])
    assert exc.value.code == 0
    assert rec.calls == []  # delegation never happened
    assert "preflight" in capsys.readouterr().out


def test_cmd_preflight_delegates_with_passthrough(monkeypatch):
    rec = _Recorder(rc=2)
    monkeypatch.setitem(sys.modules, "preflight", rec)
    rc = homelab.main(["preflight", "--skip-aws"])
    assert rc == 2
    assert rec.calls == [["--skip-aws"]]


def test_cmd_smoke_calls_module_main_no_args(monkeypatch):
    rec = _Recorder(rc=0)

    # smoke_test is imported at module level; replace the bound reference.
    class _SmokeStub:
        @staticmethod
        def main():
            rec.calls.append(None)
            return rec.rc

    monkeypatch.setattr(homelab, "smoke_test", _SmokeStub)
    rc = homelab.main(["smoke"])
    assert rc == 0
    assert rec.calls == [None]


def test_cmd_rollback_delegates_with_passthrough(monkeypatch):
    rec = _Recorder(rc=3)
    monkeypatch.setitem(sys.modules, "verify_aws_rollback", rec)
    rc = homelab.main(["rollback", "--region", "us-east-1"])
    assert rc == 3
    assert rec.calls == [["--region", "us-east-1"]]


def test_cmd_backup_pre_delegates_with_passthrough(monkeypatch):
    rec = _Recorder(rc=2)
    monkeypatch.setitem(sys.modules, "velero_pre_deploy_backup", rec)
    rc = homelab.main(["backup", "pre", "--git-sha", "abc1234"])
    assert rc == 2
    assert rec.calls == [["--git-sha", "abc1234"]]


def test_cmd_backup_verify_invokes_make(monkeypatch):
    captured = {}

    def fake_call(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return 0

    monkeypatch.setattr(homelab.subprocess, "call", fake_call)
    rc = homelab.main(["backup", "verify"])
    assert rc == 0
    assert captured["cmd"] == ["make", "test-velero-restore"]
    assert captured["cwd"] == homelab.BIN_DIR.parent


def test_cmd_drift_delegates_with_passthrough(monkeypatch):
    rec = _Recorder(rc=1)
    # drift is imported at module level — replace the bound reference.
    monkeypatch.setattr(homelab, "drift", rec)
    rc = homelab.main(["drift", "--fix"])
    assert rc == 1
    assert rec.calls == [["--fix"]]


# ── exit code propagation: not zero from module → not zero from CLI ─────────


def test_exit_code_propagates_from_handler(monkeypatch):
    rec = _Recorder(rc=42)
    monkeypatch.setitem(sys.modules, "preflight", rec)
    assert homelab.main(["preflight"]) == 42


# ── render functions (pure, file-like sink) ─────────────────────────────────


import io  # noqa: E402
import json  # noqa: E402


def test_render_argocd_diagnose_returns_0_when_synced_and_healthy():
    payload = json.dumps(
        {
            "metadata": {"name": "grafana"},
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Healthy"},
                "conditions": [],
            },
        }
    )
    buf = io.StringIO()
    rc = homelab.render_argocd_diagnose(payload, buf)
    assert rc == 0
    out = buf.getvalue()
    assert "App: grafana" in out
    assert "Sync:   Synced" in out
    assert "Health: Healthy" in out


def test_render_argocd_diagnose_returns_1_when_degraded_with_conditions():
    payload = json.dumps(
        {
            "metadata": {"name": "loki"},
            "status": {
                "sync": {"status": "OutOfSync"},
                "health": {"status": "Degraded"},
                "conditions": [{"type": "ComparisonError", "message": "boom"}],
                "operationState": {"phase": "Failed", "message": "sync failed"},
            },
        }
    )
    buf = io.StringIO()
    rc = homelab.render_argocd_diagnose(payload, buf)
    assert rc == 1
    out = buf.getvalue()
    assert "ComparisonError" in out
    assert "Last operation: Failed" in out
    assert "sync failed" in out


def test_render_argocd_diagnose_returns_2_on_invalid_json(capsys):
    buf = io.StringIO()
    rc = homelab.render_argocd_diagnose("not json", buf)
    assert rc == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_render_argocd_list_returns_0_when_all_synced(monkeypatch):
    apps = [
        SimpleNamespace(name="grafana", sync_status="Synced", health_status="Healthy"),
        SimpleNamespace(name="loki", sync_status="Synced", health_status="Healthy"),
    ]
    monkeypatch.setattr(homelab.smoke_test, "parse_argocd_apps", lambda _s: apps)
    buf = io.StringIO()
    rc = homelab.render_argocd_list("{}", buf)
    assert rc == 0
    assert "Total: 2 apps, 0 not Synced" in buf.getvalue()


def test_render_argocd_list_returns_1_when_any_degraded(monkeypatch):
    apps = [
        SimpleNamespace(name="grafana", sync_status="Synced", health_status="Healthy"),
        SimpleNamespace(name="loki", sync_status="OutOfSync", health_status="Healthy"),
    ]
    monkeypatch.setattr(homelab.smoke_test, "parse_argocd_apps", lambda _s: apps)
    buf = io.StringIO()
    rc = homelab.render_argocd_list("{}", buf)
    assert rc == 1


def test_render_argocd_list_returns_1_when_no_apps(monkeypatch):
    monkeypatch.setattr(homelab.smoke_test, "parse_argocd_apps", lambda _s: [])
    buf = io.StringIO()
    rc = homelab.render_argocd_list("{}", buf)
    assert rc == 1
    assert "No ArgoCD applications" in buf.getvalue()


def test_render_k3s_status_returns_0_when_all_ready(monkeypatch):
    nodes = [("rpi-1", "Ready", "control-plane"), ("rpi-2", "Ready", "worker")]
    monkeypatch.setattr(homelab.morning_sync, "parse_kubectl_nodes", lambda _s: nodes)
    buf = io.StringIO()
    rc = homelab.render_k3s_status("", buf)
    assert rc == 0
    assert "Total: 2 nodes, 0 not Ready" in buf.getvalue()


def test_render_k3s_status_returns_1_when_any_not_ready(monkeypatch):
    nodes = [("rpi-1", "Ready", "control-plane"), ("rpi-2", "NotReady", "worker")]
    monkeypatch.setattr(homelab.morning_sync, "parse_kubectl_nodes", lambda _s: nodes)
    buf = io.StringIO()
    rc = homelab.render_k3s_status("", buf)
    assert rc == 1


def test_render_k3s_status_returns_1_when_no_nodes(monkeypatch):
    monkeypatch.setattr(homelab.morning_sync, "parse_kubectl_nodes", lambda _s: [])
    buf = io.StringIO()
    rc = homelab.render_k3s_status("", buf)
    assert rc == 1
    assert "No nodes found" in buf.getvalue()


# ── cmd_* wrappers around _kubectl + render ─────────────────────────────────


def _fake_kubectl_proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_cmd_argocd_diagnose_returns_2_on_kubectl_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        homelab,
        "_kubectl",
        lambda *a, **kw: _fake_kubectl_proc(returncode=1, stderr="forbidden"),
    )
    args = SimpleNamespace(app="grafana", namespace="argocd", kubeconfig=None)
    assert homelab.cmd_argocd_diagnose(args) == 2
    assert "kubectl failed" in capsys.readouterr().err


def test_cmd_argocd_list_returns_2_on_kubectl_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        homelab,
        "_kubectl",
        lambda *a, **kw: _fake_kubectl_proc(returncode=1, stderr="x"),
    )
    args = SimpleNamespace(namespace="argocd", kubeconfig=None)
    assert homelab.cmd_argocd_list(args) == 2


def test_cmd_argocd_diagnose_passes_through_to_render(monkeypatch):
    payload = json.dumps(
        {
            "metadata": {"name": "x"},
            "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}},
        }
    )
    monkeypatch.setattr(
        homelab, "_kubectl", lambda *a, **kw: _fake_kubectl_proc(stdout=payload)
    )
    args = SimpleNamespace(app="x", namespace="argocd", kubeconfig=None)
    assert homelab.cmd_argocd_diagnose(args) == 0


def test_cmd_k3s_status_returns_2_on_kubectl_failure(monkeypatch):
    monkeypatch.setattr(
        homelab, "_kubectl", lambda *a, **kw: _fake_kubectl_proc(returncode=1)
    )
    args = SimpleNamespace(kubeconfig=None)
    assert homelab.cmd_k3s_status(args) == 2


# ── ci replay / tf cost / tf drift ──────────────────────────────────────────


def test_cmd_ci_replay_rejects_unknown_step(capsys):
    args = SimpleNamespace(step="this-target-does-not-exist")
    assert homelab.cmd_ci_replay(args) == 2
    assert "Unknown step" in capsys.readouterr().err


def test_cmd_ci_replay_invokes_make(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        homelab.subprocess,
        "call",
        lambda cmd, cwd=None: (captured.update(cmd=cmd, cwd=cwd) or 0),
    )
    valid_step = next(iter(homelab.CI_REPLAY_TARGETS))
    args = SimpleNamespace(step=valid_step)
    assert homelab.cmd_ci_replay(args) == 0
    assert captured["cmd"] == ["make", valid_step]


def test_cmd_tf_cost_invokes_make_show_costs(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        homelab.subprocess,
        "call",
        lambda cmd, cwd=None: (captured.update(cmd=cmd) or 0),
    )
    assert homelab.cmd_tf_cost(SimpleNamespace()) == 0
    assert captured["cmd"] == ["make", "show-costs"]


def test_cmd_tf_drift_returns_0_when_drift_pass(monkeypatch):
    fake_drift = SimpleNamespace(
        checks=[{"name": "tf.drift", "status": "pass", "message": "no drift"}],
        check_terraform=lambda: None,
        render=lambda _o: None,
    )
    monkeypatch.setattr(homelab.drift, "Drift", lambda _args: fake_drift)
    args = SimpleNamespace(summary=False, kubeconfig=None, timeout=60)
    assert homelab.cmd_tf_drift(args) == 0


def test_cmd_tf_drift_summary_emits_one_line(monkeypatch, capsys):
    fake_drift = SimpleNamespace(
        checks=[{"name": "tf.drift", "status": "fail", "message": "5 changes"}],
        check_terraform=lambda: None,
        render=lambda _o: None,
    )
    monkeypatch.setattr(homelab.drift, "Drift", lambda _args: fake_drift)
    args = SimpleNamespace(summary=True, kubeconfig=None, timeout=60)
    assert homelab.cmd_tf_drift(args) == 1
    out = capsys.readouterr().out
    assert "tf.drift" in out and "fail" in out and "5 changes" in out
