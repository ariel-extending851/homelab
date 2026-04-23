"""Tests for bin/qa_test_audit.py"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qa_test_audit as qa  # noqa: E402


FROZEN_NOW = datetime(2026, 4, 22, 10, 30, 15, tzinfo=timezone.utc)
FROZEN_RUN_ID = "20260422T103015Z"
FROZEN_TS = "2026-04-22T10:30:15Z"


def _fake_runner(status_by_suite):
    """Return a run_suite substitute that records calls and fixes status."""
    calls = []

    def _runner(suite_id, command, required, log_file, include_live_e2e):
        calls.append((suite_id, command, required, str(log_file), include_live_e2e))
        status = status_by_suite.get(suite_id, "passed")
        skip_reason = "LIVE_E2E_DISABLED" if status == "skipped" else None
        return {
            "suite": suite_id,
            "command": command,
            "required": required,
            "status": status,
            "duration_seconds": 1,
            "log": str(log_file),
            "skip_reason": skip_reason,
        }

    _runner.calls = calls
    return _runner


# ── build_test_matrix ────────────────────────────────────────────────────────


def test_matrix_base_has_seven_suites():
    assert len(qa.TESTS_BASE) == 7


def test_matrix_appends_e2e_live_required_when_flag_is_1():
    matrix = qa.build_test_matrix("1")
    assert matrix[-1] == ("e2e_live", "make test-e2e-post-deploy", "yes")
    assert len(matrix) == 8


def test_matrix_appends_e2e_live_not_required_when_flag_is_0():
    matrix = qa.build_test_matrix("0")
    assert matrix[-1] == ("e2e_live", "make test-e2e-post-deploy", "no")


def test_matrix_appends_e2e_live_not_required_for_empty_value():
    matrix = qa.build_test_matrix("")
    assert matrix[-1][2] == "no"


# ── git_info ─────────────────────────────────────────────────────────────────


def test_git_info_returns_commit_and_branch():
    def _fake_run(cmd, *args, **kwargs):
        m = MagicMock()
        if "--short" in cmd:
            m.stdout = "abc1234\n"
        else:
            m.stdout = "main\n"
        return m

    with patch("qa_test_audit.subprocess.run", side_effect=_fake_run):
        commit, branch = qa.git_info()
    assert commit == "abc1234"
    assert branch == "main"


def test_git_info_returns_unknown_on_failure():
    failure = subprocess.CalledProcessError(returncode=128, cmd=["git"])
    with patch("qa_test_audit.subprocess.run", side_effect=failure):
        commit, branch = qa.git_info()
    assert commit == "unknown"
    assert branch == "unknown"


def test_git_info_returns_unknown_when_git_not_installed():
    with patch("qa_test_audit.subprocess.run", side_effect=FileNotFoundError):
        commit, branch = qa.git_info()
    assert commit == "unknown"
    assert branch == "unknown"


# ── run_suite ────────────────────────────────────────────────────────────────


def test_run_suite_runs_command_and_marks_passed_on_zero_exit(tmp_path):
    log = tmp_path / "ok.log"
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    with patch("qa_test_audit.subprocess.run", return_value=fake_proc):
        result = qa.run_suite("contracts", "make test-contracts", "yes", log, "0")
    assert result["status"] == "passed"
    assert result["suite"] == "contracts"
    assert result["required"] == "yes"
    assert result["skip_reason"] is None
    assert result["log"] == str(log)


def test_run_suite_marks_failed_on_nonzero_exit(tmp_path):
    log = tmp_path / "fail.log"
    fake_proc = MagicMock()
    fake_proc.returncode = 2
    with patch("qa_test_audit.subprocess.run", return_value=fake_proc):
        result = qa.run_suite("shell", "make test-shell", "yes", log, "0")
    assert result["status"] == "failed"


def test_run_suite_skips_e2e_live_when_flag_not_1(tmp_path):
    log = tmp_path / "e2e.log"
    result = qa.run_suite("e2e_live", "make test-e2e-post-deploy", "no", log, "0")
    assert result["status"] == "skipped"
    assert result["skip_reason"] == "LIVE_E2E_DISABLED"
    assert "Live E2E skipped by default" in log.read_text()


def test_run_suite_runs_e2e_live_when_flag_is_1(tmp_path):
    log = tmp_path / "e2e.log"
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    with patch("qa_test_audit.subprocess.run", return_value=fake_proc) as mock_run:
        result = qa.run_suite("e2e_live", "make test-e2e-post-deploy", "yes", log, "1")
    assert result["status"] == "passed"
    assert result["skip_reason"] is None
    mock_run.assert_called_once()


def test_run_suite_uses_bash_login_shell_and_captures_output(tmp_path):
    log = tmp_path / "capture.log"
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    with patch("qa_test_audit.subprocess.run", return_value=fake_proc) as mock_run:
        qa.run_suite("contracts", "make test-contracts", "yes", log, "0")
    args = mock_run.call_args.args
    kwargs = mock_run.call_args.kwargs
    # Must invoke bash login shell (matches original `bash -lc` semantics)
    assert args[0] == ["bash", "-lc", "make test-contracts"]
    assert kwargs.get("shell") is not True  # shell=True would route via /bin/sh
    assert kwargs["stderr"] == subprocess.STDOUT


# ── render_markdown / render_json ────────────────────────────────────────────


def test_render_markdown_includes_header_and_rows(tmp_path):
    run_info = {
        "timestamp_utc": FROZEN_TS,
        "commit": "abc1234",
        "branch": "develop",
        "include_live_e2e": "0",
    }
    results = [
        {
            "suite": "contracts",
            "command": "make test-contracts",
            "required": "yes",
            "status": "passed",
            "duration_seconds": 12,
            "log": "/tmp/c.log",
            "skip_reason": None,
        }
    ]
    out = tmp_path / "summary.md"
    qa.render_markdown(run_info, results, out)
    text = out.read_text()
    assert "# QA Audit Report" in text
    assert FROZEN_TS in text
    assert "abc1234" in text
    assert "develop" in text
    assert "| contracts | make test-contracts | yes | passed | 12 |" in text


def test_render_json_produces_schema(tmp_path):
    run_info = {
        "timestamp_utc": FROZEN_TS,
        "commit": "abc",
        "branch": "b",
        "include_live_e2e": "1",
    }
    results = [
        {
            "suite": "e2e_live",
            "command": "make test-e2e-post-deploy",
            "required": "yes",
            "status": "skipped",
            "duration_seconds": 0,
            "log": "/tmp/e.log",
            "skip_reason": "LIVE_E2E_DISABLED",
        }
    ]
    out = tmp_path / "summary.json"
    qa.render_json(run_info, results, required_failures=0, out_path=out)

    payload = json.loads(out.read_text())
    assert payload["timestamp_utc"] == FROZEN_TS
    assert payload["commit"] == "abc"
    assert payload["branch"] == "b"
    assert payload["include_live_e2e"] == "1"
    assert payload["required_failures"] == 0
    assert isinstance(payload["results"], list)
    assert payload["results"][0]["skip_reason"] == "LIVE_E2E_DISABLED"


def test_render_json_serializes_null_skip_reason(tmp_path):
    out = tmp_path / "s.json"
    qa.render_json(
        run_info={
            "timestamp_utc": "t",
            "commit": "c",
            "branch": "b",
            "include_live_e2e": "0",
        },
        results=[
            {
                "suite": "x",
                "command": "y",
                "required": "no",
                "status": "passed",
                "duration_seconds": 3,
                "log": "l",
                "skip_reason": None,
            }
        ],
        required_failures=0,
        out_path=out,
    )
    assert '"skip_reason": null' in out.read_text()


# ── run_audit (end-to-end with fake runner) ──────────────────────────────────


def test_run_audit_writes_all_three_artifacts(tmp_path):
    runner = _fake_runner({})
    with patch("qa_test_audit.git_info", return_value=("deadbee", "feature/x")):
        rc = qa.run_audit(
            out_dir=tmp_path, include_live_e2e="0", now=FROZEN_NOW, runner=runner
        )
    assert rc == 0
    assert (tmp_path / f"qa-audit-{FROZEN_RUN_ID}.md").is_file()
    assert (tmp_path / f"qa-audit-{FROZEN_RUN_ID}.json").is_file()
    assert (tmp_path / "qa-audit-latest.md").is_file()
    assert (tmp_path / f"logs-{FROZEN_RUN_ID}").is_dir()


def test_run_audit_returns_1_when_required_suite_fails(tmp_path):
    runner = _fake_runner({"shell": "failed"})  # shell is required
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        rc = qa.run_audit(tmp_path, "0", now=FROZEN_NOW, runner=runner)
    assert rc == 1
    data = json.loads((tmp_path / f"qa-audit-{FROZEN_RUN_ID}.json").read_text())
    assert data["required_failures"] == 1


def test_run_audit_returns_0_when_only_optional_fails(tmp_path):
    runner = _fake_runner({"performance": "failed"})  # performance is NOT required
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        rc = qa.run_audit(tmp_path, "0", now=FROZEN_NOW, runner=runner)
    assert rc == 0


def test_run_audit_latest_md_matches_timestamped_md(tmp_path):
    runner = _fake_runner({})
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        qa.run_audit(tmp_path, "0", now=FROZEN_NOW, runner=runner)
    timestamped = (tmp_path / f"qa-audit-{FROZEN_RUN_ID}.md").read_text()
    latest = (tmp_path / "qa-audit-latest.md").read_text()
    assert latest == timestamped


def test_run_audit_counts_e2e_live_as_required_when_flag_is_1(tmp_path):
    runner = _fake_runner({"e2e_live": "failed"})
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        rc = qa.run_audit(tmp_path, "1", now=FROZEN_NOW, runner=runner)
    assert rc == 1


def test_run_audit_includes_e2e_live_as_non_required_by_default(tmp_path):
    runner = _fake_runner({"e2e_live": "failed"})
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        rc = qa.run_audit(tmp_path, "0", now=FROZEN_NOW, runner=runner)
    # e2e_live failure must not fail the audit when flag is 0
    assert rc == 0


def test_run_audit_creates_missing_output_dir(tmp_path):
    out = tmp_path / "nested" / "subdir"
    runner = _fake_runner({})
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        qa.run_audit(out, "0", now=FROZEN_NOW, runner=runner)
    assert out.is_dir()
    assert (out / f"qa-audit-{FROZEN_RUN_ID}.md").is_file()


def test_run_audit_writes_per_suite_log_paths_into_json(tmp_path):
    runner = _fake_runner({})
    with patch("qa_test_audit.git_info", return_value=("x", "y")):
        qa.run_audit(tmp_path, "0", now=FROZEN_NOW, runner=runner)
    data = json.loads((tmp_path / f"qa-audit-{FROZEN_RUN_ID}.json").read_text())
    log_paths = [r["log"] for r in data["results"]]
    assert all(f"logs-{FROZEN_RUN_ID}" in p for p in log_paths)
    assert len(data["results"]) == 8  # 7 base + e2e_live


# ── main ─────────────────────────────────────────────────────────────────────


def test_main_reads_env_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("QA_INCLUDE_LIVE_E2E", raising=False)
    monkeypatch.delenv("QA_OUT_DIR", raising=False)
    with patch("qa_test_audit.run_audit", return_value=0) as mock_audit:
        rc = qa.main()
    assert rc == 0
    assert mock_audit.call_args.args == (".qa/evidence", "0")


def test_main_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("QA_INCLUDE_LIVE_E2E", "1")
    monkeypatch.setenv("QA_OUT_DIR", "/tmp/custom")
    with patch("qa_test_audit.run_audit", return_value=1) as mock_audit:
        rc = qa.main()
    assert rc == 1
    assert mock_audit.call_args.args == ("/tmp/custom", "1")
