"""Tests for infra/aws/scripts/validate_localstack.py"""

import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import validate_localstack as tl  # noqa: E402


def _make_tester(tmp_path, env=None):
    env = dict(env or {})
    env.setdefault("PATH", "/usr/bin:/bin")
    return tl.LocalStackTester(workdir=tmp_path, env=env)


# ── log counters ─────────────────────────────────────────────────────────────


def test_log_success_increments_passed(tmp_path, capsys):
    t = _make_tester(tmp_path)
    t.log_success("ok")
    assert t.passed == 1
    assert "ok" in capsys.readouterr().out


def test_log_error_increments_failed(tmp_path, capsys):
    t = _make_tester(tmp_path)
    t.log_error("nope")
    assert t.failed == 1
    assert "nope" in capsys.readouterr().out


def test_log_warning_does_not_touch_counters(tmp_path):
    t = _make_tester(tmp_path)
    t.log_warning("careful")
    assert t.passed == 0 and t.failed == 0


# ── prerequisites: LocalStack ────────────────────────────────────────────────


def test_localstack_running_true_on_200(tmp_path):
    t = _make_tester(tmp_path)
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda *a: None
    with patch("validate_localstack.urllib.request.urlopen", return_value=fake_resp):
        ok = t.check_localstack_running()
    assert ok is True
    assert t.passed == 1


def test_localstack_running_false_on_urlerror(tmp_path):
    t = _make_tester(tmp_path)
    with patch(
        "validate_localstack.urllib.request.urlopen",
        side_effect=urllib.error.URLError("down"),
    ):
        ok = t.check_localstack_running()
    assert ok is False
    assert t.failed == 1


def test_localstack_running_false_on_oserror(tmp_path):
    t = _make_tester(tmp_path)
    with patch("validate_localstack.urllib.request.urlopen", side_effect=OSError):
        ok = t.check_localstack_running()
    assert ok is False


# ── prerequisites: tflocal detection ─────────────────────────────────────────


def test_is_executable_rejects_non_executable_file_on_path(tmp_path):
    """PATH lookup must ignore files that are not marked executable."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # File exists with the right name but is NOT executable
    (bin_dir / "tflocal").write_text("not runnable")
    t = _make_tester(tmp_path, env={"PATH": str(bin_dir)})
    with patch.object(Path, "home", return_value=tmp_path / "no-home"):
        ok = t.check_tflocal_available()
    assert ok is False
    assert t.failed == 1


def test_tflocal_found_on_path(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tf = bin_dir / "tflocal"
    tf.write_text("#!/bin/sh\nexit 0\n")
    tf.chmod(0o755)
    t = _make_tester(tmp_path, env={"PATH": str(bin_dir)})
    ok = t.check_tflocal_available()
    assert ok is True
    assert t.passed == 1


def test_tflocal_missing_reports_error(tmp_path):
    t = _make_tester(tmp_path, env={"PATH": "/nonexistent"})
    with patch.object(Path, "home", return_value=tmp_path / "no-home"):
        ok = t.check_tflocal_available()
    assert ok is False
    assert t.failed == 1


def test_tflocal_found_in_mise_shims(tmp_path):
    fake_home = tmp_path / "home"
    shims = fake_home / ".local/share/mise/shims"
    shims.mkdir(parents=True)
    tf = shims / "tflocal"
    tf.write_text("")
    tf.chmod(0o755)
    t = _make_tester(tmp_path, env={"PATH": "/nonexistent"})
    with patch.object(Path, "home", return_value=fake_home):
        ok = t.check_tflocal_available()
    assert ok is True
    assert str(shims) in t.env["PATH"]


# ── prerequisites: SOPS detection ────────────────────────────────────────────


def test_sops_configured_when_key_file_exists(tmp_path):
    key = tmp_path / "age.txt"
    key.write_text("AGE-SECRET-KEY-...\n")
    t = _make_tester(tmp_path, env={"SOPS_AGE_KEY_FILE": str(key)})
    t.check_sops_configured()
    assert t.sops_enabled is True
    assert t.env["SOPS_ENABLED"] == "true"


def test_sops_not_configured_when_env_missing(tmp_path):
    t = _make_tester(tmp_path, env={})
    t.check_sops_configured()
    assert t.sops_enabled is False
    assert t.env["SOPS_ENABLED"] == "false"


def test_sops_not_configured_when_key_file_missing(tmp_path):
    t = _make_tester(tmp_path, env={"SOPS_AGE_KEY_FILE": str(tmp_path / "nope")})
    t.check_sops_configured()
    assert t.sops_enabled is False


# ── individual tflocal tests ─────────────────────────────────────────────────


def test_test_init_success(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=0):
        ok = t.test_init()
    assert ok is True
    assert t.passed == 1


def test_test_init_failure_prints_log(tmp_path, capsys):
    t = _make_tester(tmp_path)
    (tl.LOG_DIR / "tf-init.log").write_text("boom")
    with patch.object(t, "_run_logged", return_value=1):
        ok = t.test_init()
    assert ok is False
    assert t.failed == 1


def test_test_validate_success(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=0):
        assert t.test_validate() is True


def test_test_validate_failure(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        assert t.test_validate() is False
    assert t.failed == 1


def test_test_get_success_counts_modules(tmp_path):
    t = _make_tester(tmp_path)
    (tmp_path / "modules" / "compute").mkdir(parents=True)
    (tmp_path / "modules" / "network").mkdir()
    with patch.object(t, "_run_logged", return_value=0):
        assert t.test_get() is True
    assert t.passed == 1


def test_test_get_failure(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        assert t.test_get() is False


def test_test_plan_counts_resources(tmp_path):
    t = _make_tester(tmp_path)
    fake_show = MagicMock()
    fake_show.returncode = 0
    fake_show.stdout = json.dumps({"resource_changes": [{}, {}, {}]})
    with patch.object(t, "_run_logged", return_value=0), patch.object(
        t, "_run_capture", return_value=fake_show
    ):
        assert t.test_plan() is True
    assert t.passed == 1


def test_test_plan_handles_show_failure(tmp_path):
    t = _make_tester(tmp_path)
    fake_show = MagicMock()
    fake_show.returncode = 1
    fake_show.stdout = ""
    with patch.object(t, "_run_logged", return_value=0), patch.object(
        t, "_run_capture", return_value=fake_show
    ):
        assert t.test_plan() is True  # plan still succeeded


def test_test_plan_handles_invalid_json_from_show(tmp_path):
    t = _make_tester(tmp_path)
    fake_show = MagicMock()
    fake_show.returncode = 0
    fake_show.stdout = "not-json"
    with patch.object(t, "_run_logged", return_value=0), patch.object(
        t, "_run_capture", return_value=fake_show
    ):
        assert t.test_plan() is True


def test_test_plan_failure(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        assert t.test_plan() is False


def test_test_graph_success(tmp_path):
    t = _make_tester(tmp_path)
    graph_path = tmp_path / "terraform-graph.dot"

    def write_graph(args, log_path, extra_env=None):
        log_path.write_text("label1\nlabel2\nlabel3\n")
        return 0

    with patch.object(t, "_run_logged", side_effect=write_graph):
        t.test_graph()
    assert graph_path.is_file()
    assert t.passed == 1


def test_test_graph_failure(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        t.test_graph()
    assert t.failed == 1


def test_test_output_success_counts_pass(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=0):
        t.test_output()
    assert t.passed == 1


def test_test_output_failure_only_warns(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        t.test_output()
    assert t.passed == 0 and t.failed == 0  # warning only


def test_test_apply_success(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=0):
        t.test_apply()
    assert t.passed == 1


def test_test_apply_failure_only_warns(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        t.test_apply()
    assert t.failed == 0  # apply failures are tolerated


# ── state assertions ────────────────────────────────────────────────────────


def test_state_assertions_all_present(tmp_path):
    t = _make_tester(tmp_path)
    state = (
        "aws_iam_role.a\n"
        "aws_iam_role.b\n"
        "aws_lambda_function.scheduler\n"
        "aws_security_group.k3s\n"
        "aws_s3_bucket.ssm_transfer\n"
        "aws_iam_instance_profile.k3s\n"
    )

    def write_state(args, log_path, extra_env=None):
        log_path.write_text(state)
        return 0

    with patch.object(t, "_run_logged", side_effect=write_state):
        t.test_state_assertions()
    # 5 assertions (iam_roles, lambda, sg, s3, instance_profile)
    assert t.passed == 5
    assert t.failed == 0


def test_state_assertions_missing_lambda(tmp_path):
    t = _make_tester(tmp_path)
    state = (
        "aws_iam_role.a\n"
        "aws_iam_role.b\n"
        "aws_security_group.k3s\n"
        "aws_s3_bucket.ssm_transfer\n"
        "aws_iam_instance_profile.k3s\n"
    )

    def write_state(args, log_path, extra_env=None):
        log_path.write_text(state)
        return 0

    with patch.object(t, "_run_logged", side_effect=write_state):
        t.test_state_assertions()
    assert t.failed >= 1


def test_state_assertions_iam_count_below_minimum(tmp_path):
    t = _make_tester(tmp_path)
    state = (
        "aws_iam_role.only_one\n"
        "aws_lambda_function.scheduler\n"
        "aws_security_group.k3s\n"
        "aws_s3_bucket.ssm_transfer\n"
        "aws_iam_instance_profile.k3s\n"
    )

    def write_state(args, log_path, extra_env=None):
        log_path.write_text(state)
        return 0

    with patch.object(t, "_run_logged", side_effect=write_state):
        t.test_state_assertions()
    # Only 1 IAM role found, minimum is 2 → 1 failure
    assert t.failed == 1


# ── cleanup ─────────────────────────────────────────────────────────────────


def test_cleanup_destroy_success(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=0):
        t.cleanup_destroy()
    assert t.passed == 1


def test_cleanup_destroy_failure_only_warns(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        t.cleanup_destroy()
    assert t.failed == 0


# ── _run_logged / _run_capture ──────────────────────────────────────────────


def test_run_logged_writes_to_log_and_returns_exitcode(tmp_path):
    t = _make_tester(tmp_path)
    log_path = tmp_path / "ok.log"
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    with patch(
        "validate_localstack.subprocess.run", return_value=fake_proc
    ) as mock_run:
        rc = t._run_logged(["tflocal", "init"], log_path)
    assert rc == 0
    kwargs = mock_run.call_args.kwargs
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stderr"] == subprocess.STDOUT


def test_run_capture_returns_completed_process(tmp_path):
    t = _make_tester(tmp_path)
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = "hello"
    fake.stderr = ""
    with patch("validate_localstack.subprocess.run", return_value=fake):
        result = t._run_capture(["tflocal", "show"])
    assert result.stdout == "hello"


# ── orchestrator (run) ──────────────────────────────────────────────────────


def _patch_all_stages(t, return_values):
    """Helper to patch each stage method on the tester instance."""
    stubs = {}
    for method, rv in return_values.items():
        stubs[method] = patch.object(t, method, return_value=rv)
    return stubs


def test_run_exits_1_when_localstack_not_running(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "check_localstack_running", return_value=False):
        rc = t.run()
    assert rc == 1


def test_run_exits_1_when_tflocal_missing(tmp_path):
    t = _make_tester(tmp_path)
    with patch.object(t, "check_localstack_running", return_value=True), patch.object(
        t, "check_tflocal_available", return_value=False
    ):
        rc = t.run()
    assert rc == 1


def test_run_exits_1_when_test_init_fails(tmp_path):
    t = _make_tester(tmp_path)
    patches = [
        patch.object(t, "check_localstack_running", return_value=True),
        patch.object(t, "check_tflocal_available", return_value=True),
        patch.object(t, "check_sops_configured"),
        patch.object(t, "test_init", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        rc = t.run()
    finally:
        for p in patches:
            p.stop()
    assert rc == 1


def test_run_completes_full_sequence_when_all_pass(tmp_path):
    t = _make_tester(tmp_path)
    patches = [
        patch.object(t, "check_localstack_running", return_value=True),
        patch.object(t, "check_tflocal_available", return_value=True),
        patch.object(t, "check_sops_configured"),
        patch.object(t, "test_init", return_value=True),
        patch.object(t, "test_validate", return_value=True),
        patch.object(t, "test_get", return_value=True),
        patch.object(t, "test_plan", return_value=True),
        patch.object(t, "test_graph"),
        patch.object(t, "test_output"),
        patch.object(t, "test_apply"),
        patch.object(t, "test_output_schema_post_apply"),
        patch.object(t, "test_state_assertions"),
        patch.object(t, "cleanup_destroy"),
    ]
    for p in patches:
        p.start()
    try:
        rc = t.run()
    finally:
        for p in patches:
            p.stop()
    assert rc == 0


def test_run_returns_1_when_failures_recorded(tmp_path):
    t = _make_tester(tmp_path)
    patches = [
        patch.object(t, "check_localstack_running", return_value=True),
        patch.object(t, "check_tflocal_available", return_value=True),
        patch.object(t, "check_sops_configured"),
        patch.object(t, "test_init", return_value=True),
        patch.object(t, "test_validate", return_value=True),
        patch.object(t, "test_get", return_value=True),
        patch.object(t, "test_plan", return_value=True),
        patch.object(t, "test_graph"),
        patch.object(t, "test_output"),
        patch.object(t, "test_apply"),
        patch.object(t, "test_output_schema_post_apply"),
        patch.object(t, "test_state_assertions"),
        patch.object(t, "cleanup_destroy"),
    ]
    for p in patches:
        p.start()
    t.failed = 2  # simulate state assertion failures
    try:
        rc = t.run()
    finally:
        for p in patches:
            p.stop()
    assert rc == 1


# ── main ────────────────────────────────────────────────────────────────────


def test_main_delegates_to_tester():
    with patch("validate_localstack.LocalStackTester") as mock_cls:
        mock_cls.return_value.run.return_value = 0
        rc = tl.main()
    assert rc == 0
    mock_cls.assert_called_once()


# ── additional branch-coverage tests ────────────────────────────────────────


def test_localstack_running_false_on_non_2xx_status(tmp_path):
    """Line 66->71 branch: status outside 2xx range."""
    t = _make_tester(tmp_path)
    fake_resp = MagicMock()
    fake_resp.status = 503
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda *a: None
    with patch("validate_localstack.urllib.request.urlopen", return_value=fake_resp):
        ok = t.check_localstack_running()
    assert ok is False
    assert t.failed == 1


def test_run_logged_applies_extra_env(tmp_path):
    """Line 125 branch: env.update(extra_env) when extra_env is set."""
    t = _make_tester(tmp_path)
    log_path = tmp_path / "log.txt"
    recorded = {}

    def _run(args, *a, **kw):
        recorded["env"] = kw.get("env", {})
        r = MagicMock()
        r.returncode = 0
        return r

    with patch("validate_localstack.subprocess.run", side_effect=_run):
        t._run_logged(["tflocal", "x"], log_path, extra_env={"TF_VAR_x": "y"})
    assert recorded["env"]["TF_VAR_x"] == "y"


def test_run_capture_applies_extra_env_and_writes_log(tmp_path):
    """Line 136 and 145: extra_env merge + log_path tee."""
    t = _make_tester(tmp_path)
    log_path = tmp_path / "captured.log"
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = "out\n"
    fake.stderr = "err\n"
    with patch("validate_localstack.subprocess.run", return_value=fake):
        t._run_capture(["tflocal", "show"], log_path=log_path, extra_env={"K": "V"})
    content = log_path.read_text()
    assert "out" in content
    assert "err" in content


def test_test_graph_handles_oserror_reading_graph(tmp_path):
    """Line 228-229 branch: OSError when reading graph.dot."""
    t = _make_tester(tmp_path)
    graph_path = tmp_path / "terraform-graph.dot"

    def write_graph(args, log_path, extra_env=None):
        # intentionally don't create the graph file — read_text will raise
        return 0

    with patch.object(t, "_run_logged", side_effect=write_graph):
        t.test_graph()
    # graph still counted as success despite read failure
    assert t.passed == 1


def test_test_state_assertions_handles_oserror_reading_state_log(tmp_path):
    """Line 268-269 branch: OSError when reading state log."""
    t = _make_tester(tmp_path)

    def noop_run(args, log_path, extra_env=None):
        return 0  # don't actually write the log

    with patch.object(t, "_run_logged", side_effect=noop_run), patch.object(
        Path, "read_text", side_effect=OSError("missing")
    ):
        t.test_state_assertions()
    # all 5 assertions should fail because state_text == ""
    assert t.failed == 5


def test_run_returns_1_when_validate_fails(tmp_path):
    """Line 352 branch."""
    t = _make_tester(tmp_path)
    patches = [
        patch.object(t, "check_localstack_running", return_value=True),
        patch.object(t, "check_tflocal_available", return_value=True),
        patch.object(t, "check_sops_configured"),
        patch.object(t, "test_init", return_value=True),
        patch.object(t, "test_validate", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        rc = t.run()
    finally:
        for p in patches:
            p.stop()
    assert rc == 1


def test_run_returns_1_when_get_fails(tmp_path):
    """Line 354 branch."""
    t = _make_tester(tmp_path)
    patches = [
        patch.object(t, "check_localstack_running", return_value=True),
        patch.object(t, "check_tflocal_available", return_value=True),
        patch.object(t, "check_sops_configured"),
        patch.object(t, "test_init", return_value=True),
        patch.object(t, "test_validate", return_value=True),
        patch.object(t, "test_get", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        rc = t.run()
    finally:
        for p in patches:
            p.stop()
    assert rc == 1


def test_run_returns_1_when_plan_fails(tmp_path):
    """Line 356 branch."""
    t = _make_tester(tmp_path)
    patches = [
        patch.object(t, "check_localstack_running", return_value=True),
        patch.object(t, "check_tflocal_available", return_value=True),
        patch.object(t, "check_sops_configured"),
        patch.object(t, "test_init", return_value=True),
        patch.object(t, "test_validate", return_value=True),
        patch.object(t, "test_get", return_value=True),
        patch.object(t, "test_plan", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        rc = t.run()
    finally:
        for p in patches:
            p.stop()
    assert rc == 1


def test_is_executable_falls_back_to_defpath_when_path_empty(tmp_path):
    """Line 104 branch: `(self.env.get("PATH", "") or os.defpath)` — empty PATH triggers fallback."""
    t = _make_tester(tmp_path, env={"PATH": ""})
    # Must not crash; returns a bool either way (depends on whether the
    # lookup finds the binary in os.defpath).
    assert isinstance(t._is_executable("ls"), bool)


def test_is_executable_handles_empty_segment_in_path(tmp_path):
    """Line 105->104 branch: empty directory segment in PATH (e.g. leading colon)."""
    # Leading colon → "" is the first PATH segment → `if directory:` is False
    # → must skip without crashing, then continue to /nonexistent (also no match)
    t = _make_tester(tmp_path, env={"PATH": ":/nonexistent"})
    assert t._is_executable("definitely-not-a-real-binary-xyz") is False


# ── test_output_schema_post_apply (Tier 2: LocalStack integration) ──────────


def test_output_schema_warns_and_returns_when_tflocal_fails(tmp_path, capsys):
    """If tflocal output exits non-zero, method logs a warning and returns (no crash)."""
    t = _make_tester(tmp_path)
    with patch.object(t, "_run_logged", return_value=1):
        t.test_output_schema_post_apply()
    out = capsys.readouterr().out
    assert "Output JSON not available" in out
    # Must not increment failure counter (warning only)
    assert t.failed == 0


def test_output_schema_flags_missing_inventory_keys(tmp_path, capsys):
    """If terraform output JSON lacks inventory keys, logs error."""
    t = _make_tester(tmp_path)
    # Write fake output JSON missing several required keys
    output_log = tl.LOG_DIR / "tf-output-json.log"
    output_log.write_text(
        json.dumps(
            {
                "k3s_server_public_ip": {"value": "1.2.3.4", "type": "string"},
                # missing: k3s_server_private_ip, k3s_server_instance_id, agent keys
            }
        )
    )
    try:
        with patch.object(t, "_run_logged", return_value=0):
            t.test_output_schema_post_apply()
    finally:
        try:
            output_log.unlink()
        except FileNotFoundError:
            pass
    out = capsys.readouterr().out
    assert "missing inventory keys" in out
    assert t.failed >= 1


def test_output_schema_succeeds_when_all_keys_present(tmp_path, capsys):
    """Happy path: all 6 inventory keys present → logs success, no failure increment."""
    t = _make_tester(tmp_path)
    output_log = tl.LOG_DIR / "tf-output-json.log"
    output_log.write_text(
        json.dumps(
            {
                "k3s_server_public_ip": {"value": "1.2.3.4", "type": "string"},
                "k3s_server_private_ip": {"value": "10.0.0.1", "type": "string"},
                "k3s_server_instance_id": {"value": "i-abc", "type": "string"},
                "k3s_agent_public_ip": {"value": "5.6.7.8", "type": "string"},
                "k3s_agent_private_ip": {"value": "10.0.0.2", "type": "string"},
                "k3s_agent_instance_id": {"value": "i-def", "type": "string"},
            }
        )
    )
    try:
        with patch.object(t, "_run_logged", return_value=0):
            t.test_output_schema_post_apply()
    finally:
        try:
            output_log.unlink()
        except FileNotFoundError:
            pass
    out = capsys.readouterr().out
    assert "inventory keys present" in out
    assert t.failed == 0


def test_output_schema_logs_error_on_invalid_json(tmp_path, capsys):
    """If tflocal produces malformed JSON, method logs error (exception branch)."""
    t = _make_tester(tmp_path)
    output_log = tl.LOG_DIR / "tf-output-json.log"
    output_log.write_text("{not valid json")
    try:
        with patch.object(t, "_run_logged", return_value=0):
            t.test_output_schema_post_apply()
    finally:
        try:
            output_log.unlink()
        except FileNotFoundError:
            pass
    out = capsys.readouterr().out
    assert "Failed to parse terraform output JSON" in out
    assert t.failed >= 1


def test_output_schema_handles_unreadable_log_file(tmp_path, capsys):
    """If log file can't be read (edge case), falls back to empty string + fails parse."""
    t = _make_tester(tmp_path)
    output_log = tl.LOG_DIR / "tf-output-json.log"
    # Ensure log does not exist before test
    try:
        output_log.unlink()
    except FileNotFoundError:
        pass

    # _run_logged returns 0, but the log file is absent → read_text raises OSError
    with patch.object(t, "_run_logged", return_value=0):
        t.test_output_schema_post_apply()
    # Empty string parses as {} → missing keys → failure
    out = capsys.readouterr().out
    assert "missing" in out.lower() or "failed" in out.lower()
