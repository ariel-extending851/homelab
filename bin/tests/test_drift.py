"""Tests for bin/drift.py — verifies Argo reuse, exit-code mapping, skip flags."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drift  # noqa: E402


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _args(**overrides):
    defaults = dict(
        skip_tf=True,
        skip_argo=True,
        skip_inventory=True,
        output="text",
        kubeconfig=None,
        timeout=5,
    )
    defaults.update(overrides)
    return type("A", (), defaults)()


# ── exit-code mapping ────────────────────────────────────────────────────────


def test_exit_code_clean():
    d = drift.Drift(_args())
    d.pass_("x")
    assert d.exit_code() == 0


def test_exit_code_fail():
    d = drift.Drift(_args())
    d.fail("tf.drift", "changes")
    assert d.exit_code() == 1


def test_exit_code_warn_only():
    d = drift.Drift(_args())
    d.warn("inventory.drift", "empty")
    assert d.exit_code() == 2


# ── rendering ────────────────────────────────────────────────────────────────


def test_render_text():
    d = drift.Drift(_args())
    d.pass_("tf.drift", "clean")
    buf = io.StringIO()
    d.render(buf)
    out = buf.getvalue()
    assert "▶ drift" in out
    assert "tf.drift" in out
    assert "1 pass" in out


def test_render_json():
    d = drift.Drift(_args(output="json"))
    d.fail("argo.drift", "2/3 unhealthy")
    buf = io.StringIO()
    d.render(buf)
    doc = json.loads(buf.getvalue())
    assert doc["command"] == "drift"
    assert doc["checks"][0]["status"] == "fail"


# ── skip flags ───────────────────────────────────────────────────────────────


def test_skip_all_flags():
    d = drift.Drift(_args())
    d.run_all()
    statuses = {c["name"]: c["status"] for c in d.checks}
    assert statuses == {
        "tf.drift": "skip",
        "argo.drift": "skip",
        "inventory.drift": "skip",
    }


# ── Terraform drift ──────────────────────────────────────────────────────────


@patch("drift.subprocess.run")
def test_check_terraform_no_drift(mock_run, monkeypatch, tmp_path):
    monkeypatch.setattr(drift, "TERRAFORM_DIR", tmp_path)
    # init → 0, plan → 0 (clean)
    mock_run.side_effect = [_proc(0), _proc(0)]
    d = drift.Drift(_args(skip_tf=False))
    d.check_terraform()
    assert d.checks[-1] == {"name": "tf.drift", "status": "pass", "message": "no drift"}


@patch("drift.subprocess.run")
def test_check_terraform_drift_detected(mock_run, monkeypatch, tmp_path):
    monkeypatch.setattr(drift, "TERRAFORM_DIR", tmp_path)
    # init → 0, plan → 2 (drift)
    mock_run.side_effect = [_proc(0), _proc(2, "changes outside of Terraform")]
    d = drift.Drift(_args(skip_tf=False))
    d.check_terraform()
    assert d.checks[-1]["status"] == "fail"
    assert "drift detected" in d.checks[-1]["message"]


@patch("drift.subprocess.run")
def test_check_terraform_init_error(mock_run, monkeypatch, tmp_path):
    monkeypatch.setattr(drift, "TERRAFORM_DIR", tmp_path)
    mock_run.side_effect = [_proc(1, "", "backend config invalid")]
    d = drift.Drift(_args(skip_tf=False))
    d.check_terraform()
    assert d.checks[-1]["status"] == "fail"


def test_check_terraform_skip_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(drift, "TERRAFORM_DIR", tmp_path / "does-not-exist")
    d = drift.Drift(_args(skip_tf=False))
    d.check_terraform()
    assert d.checks[-1]["status"] == "skip"


# ── ArgoCD drift (reuses smoke_test.parse_argocd_apps) ───────────────────────


def _argocd_items(items):
    return json.dumps({"items": items})


def _argo_app(name, sync="Synced", health="Healthy"):
    return {
        "metadata": {"name": name},
        "status": {
            "sync": {"status": sync},
            "health": {"status": health},
        },
    }


@patch("drift.subprocess.run")
def test_check_argo_all_healthy(mock_run):
    mock_run.return_value = _proc(0, _argocd_items([_argo_app("a"), _argo_app("b")]))
    d = drift.Drift(_args(skip_argo=False))
    d.check_argo()
    assert d.checks[-1]["status"] == "pass"
    assert "2 apps all Synced+Healthy" in d.checks[-1]["message"]


@patch("drift.subprocess.run")
def test_check_argo_out_of_sync(mock_run):
    mock_run.return_value = _proc(
        0,
        _argocd_items(
            [
                _argo_app("a"),
                _argo_app("b", sync="OutOfSync", health="Healthy"),
                _argo_app("c", sync="Synced", health="Degraded"),
            ]
        ),
    )
    d = drift.Drift(_args(skip_argo=False))
    d.check_argo()
    last = d.checks[-1]
    assert last["status"] == "fail"
    assert "2/3 not Synced+Healthy" in last["message"]
    assert "b(" in last["message"] and "c(" in last["message"]


@patch("drift.subprocess.run")
def test_check_argo_empty_cluster_warns(mock_run):
    mock_run.return_value = _proc(0, _argocd_items([]))
    d = drift.Drift(_args(skip_argo=False))
    d.check_argo()
    assert d.checks[-1]["status"] == "warn"


@patch("drift.subprocess.run")
def test_check_argo_kubectl_error(mock_run):
    mock_run.return_value = _proc(1, "", "connection refused")
    d = drift.Drift(_args(skip_argo=False))
    d.check_argo()
    assert d.checks[-1]["status"] == "fail"


def test_argo_parser_is_reused_from_smoke_test():
    # Guards against accidental re-implementation: drift must go through smoke_test.
    import smoke_test

    assert drift.smoke_test is smoke_test
    parsed = smoke_test.parse_argocd_apps(_argocd_items([_argo_app("a")]))
    assert len(parsed) == 1 and parsed[0].name == "a"


# ── Inventory drift ──────────────────────────────────────────────────────────


@patch("drift.subprocess.run")
def test_check_inventory_populated(mock_run, monkeypatch, tmp_path):
    script = tmp_path / "inv.py"
    script.write_text("")
    monkeypatch.setattr(drift, "INVENTORY_SCRIPT", script)
    payload = {"_meta": {"hostvars": {"h1": {}, "h2": {}}}}
    mock_run.return_value = _proc(0, json.dumps(payload))
    d = drift.Drift(_args(skip_inventory=False))
    d.check_inventory()
    assert d.checks[-1]["status"] == "pass"
    assert "2 host" in d.checks[-1]["message"]


@patch("drift.subprocess.run")
def test_check_inventory_empty_warns(mock_run, monkeypatch, tmp_path):
    script = tmp_path / "inv.py"
    script.write_text("")
    monkeypatch.setattr(drift, "INVENTORY_SCRIPT", script)
    mock_run.return_value = _proc(0, json.dumps({"_meta": {"hostvars": {}}}))
    d = drift.Drift(_args(skip_inventory=False))
    d.check_inventory()
    assert d.checks[-1]["status"] == "warn"


@patch("drift.subprocess.run")
def test_check_inventory_bad_json_warns(mock_run, monkeypatch, tmp_path):
    script = tmp_path / "inv.py"
    script.write_text("")
    monkeypatch.setattr(drift, "INVENTORY_SCRIPT", script)
    mock_run.return_value = _proc(0, "not json")
    d = drift.Drift(_args(skip_inventory=False))
    d.check_inventory()
    assert d.checks[-1]["status"] == "warn"


def test_check_inventory_skip_missing_script(monkeypatch, tmp_path):
    monkeypatch.setattr(drift, "INVENTORY_SCRIPT", tmp_path / "nope.py")
    d = drift.Drift(_args(skip_inventory=False))
    d.check_inventory()
    assert d.checks[-1]["status"] == "skip"


# ── argparse ─────────────────────────────────────────────────────────────────


def test_build_arg_parser_defaults():
    args = drift.build_arg_parser().parse_args([])
    assert args.skip_tf is False
    assert args.skip_argo is False
    assert args.skip_inventory is False
    assert args.output == "text"


def test_main_all_skipped_returns_zero():
    code = drift.main(["--skip-tf", "--skip-argo", "--skip-inventory", "-o", "json"])
    assert code == 0


# ── --fix / --no-fix flags ───────────────────────────────────────────────────


def test_arg_parser_fix_flags():
    p = drift.build_arg_parser()
    args = p.parse_args(["--fix"])
    assert args.fix is True
    assert args.no_fix is False

    args = p.parse_args(["--no-fix"])
    assert args.no_fix is True
    assert args.fix is False


def test_fix_and_no_fix_are_mutually_exclusive():
    import subprocess as _sp
    result = _sp.run(
        ["python3", str(Path(__file__).resolve().parents[1] / "drift.py"), "--fix", "--no-fix"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


# ── offer_fixes: no-fix / no drift ──────────────────────────────────────────


def test_offer_fixes_no_drift_returns_zero():
    d = drift.Drift(_args(no_fix=True))
    d.pass_("tf.drift", "clean")
    assert d.offer_fixes(io.StringIO()) == 0


def test_offer_fixes_no_fix_flag_skips_prompt():
    d = drift.Drift(_args(no_fix=True))
    d._tf_drifted = True
    buf = io.StringIO()
    rc = d.offer_fixes(buf)
    # --no-fix: no prompt, no fix, exit code unchanged (1 because no checks added yet)
    assert rc == 0  # exit_code() with no checks = 0
    assert buf.getvalue() == ""


def test_offer_fixes_non_tty_prints_hint(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO())  # non-TTY
    d = drift.Drift(_args())
    d.fail("tf.drift", "drift")
    d._tf_drifted = True
    buf = io.StringIO()
    rc = d.offer_fixes(buf)
    assert rc == 1
    assert "--fix" in buf.getvalue()


# ── offer_fixes: --fix auto-applies ─────────────────────────────────────────


@patch("drift.subprocess.run")
def test_offer_fixes_fix_flag_runs_tf_apply(mock_run):
    mock_run.return_value = _proc(0)
    d = drift.Drift(_args(fix=True))
    d.fail("tf.drift", "drift")
    d._tf_drifted = True
    buf = io.StringIO()
    rc = d.offer_fixes(buf)
    assert rc == 0
    assert "terraform" in buf.getvalue()
    # subprocess.run called once for apply
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "apply" in cmd
    assert "-refresh-only" in cmd


@patch("drift.subprocess.run")
def test_offer_fixes_fix_flag_runs_argo_sync_with_argocd_cli(mock_run, monkeypatch):
    monkeypatch.setattr(drift, "_which", lambda cmd: "/usr/bin/argocd" if cmd == "argocd" else None)
    mock_run.return_value = _proc(0)
    d = drift.Drift(_args(fix=True))
    d.fail("argo.drift", "bad")
    d._argo_drifted_apps = ["myapp", "otherapp"]
    buf = io.StringIO()
    rc = d.offer_fixes(buf)
    assert rc == 0
    assert mock_run.call_count == 2
    for call in mock_run.call_args_list:
        cmd = call[0][0]
        assert cmd[0] == "argocd"
        assert "sync" in cmd


@patch("drift.subprocess.run")
def test_offer_fixes_kubectl_fallback_when_no_argocd_cli(mock_run, monkeypatch):
    monkeypatch.setattr(drift, "_which", lambda _cmd: None)
    mock_run.return_value = _proc(0)
    d = drift.Drift(_args(fix=True))
    d.fail("argo.drift", "bad")
    d._argo_drifted_apps = ["myapp"]
    buf = io.StringIO()
    rc = d.offer_fixes(buf)
    assert rc == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "kubectl"
    assert "argocd.argoproj.io/refresh=hard" in cmd


@patch("drift.subprocess.run")
def test_offer_fixes_fix_tf_failure_returns_nonzero(mock_run):
    mock_run.return_value = _proc(1, "", "apply failed")
    d = drift.Drift(_args(fix=True))
    d.fail("tf.drift", "drift")
    d._tf_drifted = True
    buf = io.StringIO()
    rc = d.offer_fixes(buf)
    assert rc == 1


# ── _count_tf_changed_resources ─────────────────────────────────────────────


def test_count_tf_changed_resources_empty():
    assert drift._count_tf_changed_resources("") == 0


def test_count_tf_changed_resources_two_resources():
    plan = (
        "  # aws_instance.foo has changed\n"
        "  # aws_security_group.bar has changed\n"
        "  ~ resource_type = old -> new\n"
    )
    assert drift._count_tf_changed_resources(plan) == 2


def test_count_tf_changed_resources_ignores_unrelated_lines():
    plan = "Terraform will perform the following actions:\n  # aws_vpc.main has changed\n"
    assert drift._count_tf_changed_resources(plan) == 1


# ── tf.drift message includes resource count ─────────────────────────────────


@patch("drift.subprocess.run")
def test_check_terraform_drift_message_includes_count(mock_run, monkeypatch, tmp_path):
    monkeypatch.setattr(drift, "TERRAFORM_DIR", tmp_path)
    plan_output = (
        "  # aws_instance.foo has changed\n"
        "  # aws_s3_bucket.bar has changed\n"
    )
    mock_run.side_effect = [_proc(0), _proc(2, plan_output)]
    d = drift.Drift(_args(skip_tf=False))
    d.check_terraform()
    msg = d.checks[-1]["message"]
    assert "drift detected" in msg
    assert "2 resource(s)" in msg
    assert d._tf_drifted is True


# ── argo drifted apps list populated ────────────────────────────────────────


@patch("drift.subprocess.run")
def test_check_argo_populates_drifted_apps_list(mock_run):
    mock_run.return_value = _proc(
        0,
        _argocd_items(
            [
                _argo_app("ok"),
                _argo_app("bad1", sync="OutOfSync"),
                _argo_app("bad2", health="Degraded"),
            ]
        ),
    )
    d = drift.Drift(_args(skip_argo=False))
    d.check_argo()
    assert set(d._argo_drifted_apps) == {"bad1", "bad2"}


@patch("drift.subprocess.run")
def test_check_argo_healthy_leaves_drifted_list_empty(mock_run):
    mock_run.return_value = _proc(0, _argocd_items([_argo_app("a"), _argo_app("b")]))
    d = drift.Drift(_args(skip_argo=False))
    d.check_argo()
    assert d._argo_drifted_apps == []
