"""Tests for bin/velero_pre_deploy_backup.py.

Mirrors the 4 scenarios from the predecessor bats suite plus extra
coverage of the GITHUB_OUTPUT contract used by the calling CI job.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import velero_pre_deploy_backup as backup  # noqa: E402


# ── helpers to fake subprocess.run with per-arg-pattern responses ───────────


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class FakeRunner:
    """Match subprocess.run(args=[...]) calls and return canned results.

    Patterns are matched by substring against the joined argv. First match
    wins; unmatched calls return returncode=0 (silent success) so callers
    only have to override what they care about.
    """

    def __init__(self, patterns):
        self.patterns = patterns
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        joined = " ".join(args) if isinstance(args, list) else str(args)
        for needle, result in self.patterns.items():
            if needle in joined:
                if isinstance(result, Exception):
                    raise result
                return result
        return _completed()


# ── reachability gates: skip silently ──────────────────────────────────────


def test_skip_when_cluster_unreachable(capsys, monkeypatch):
    runner = FakeRunner({"cluster-info": _completed(returncode=1)})
    monkeypatch.setattr(backup.subprocess, "run", runner)
    rc = backup.main(["--git-sha", "abc1234"])
    assert rc == 2  # loud skip, not silent success
    captured = capsys.readouterr()
    assert "Cluster unreachable" in captured.err  # warning on stderr
    assert "Rollback safety reduced" in captured.out  # GH annotation on stdout
    assert "::warning ::" in captured.out
    # Crucially: no `velero backup create` should have been issued.
    assert not any(
        "backup" in " ".join(c) and "create" in " ".join(c) for c in runner.calls
    )


def test_skip_when_velero_not_installed(capsys, monkeypatch):
    runner = FakeRunner(
        {
            "cluster-info": _completed(),
            "get deployment velero": _completed(returncode=1),
        }
    )
    monkeypatch.setattr(backup.subprocess, "run", runner)
    monkeypatch.setattr(backup.shutil, "which", lambda _x: "/usr/local/bin/velero")
    rc = backup.main(["--git-sha", "abc1234"])
    assert rc == 2  # loud skip, not silent success
    captured = capsys.readouterr()
    assert "Velero not installed" in captured.err
    assert "Install Velero to enable rollback safety" in captured.out
    assert "::warning ::" in captured.out
    assert not any(
        "backup" in " ".join(c) and "create" in " ".join(c) for c in runner.calls
    )


# ── velero CLI missing while cluster is up = real error ─────────────────────


def test_fail_when_velero_cli_missing(capsys, monkeypatch):
    runner = FakeRunner(
        {
            "cluster-info": _completed(),
            "get deployment velero": _completed(),
        }
    )
    monkeypatch.setattr(backup.subprocess, "run", runner)
    monkeypatch.setattr(backup.shutil, "which", lambda _x: None)
    rc = backup.main(["--git-sha", "abc1234"])
    assert rc == 1
    assert "velero CLI not in PATH" in capsys.readouterr().err


# ── happy path: backup created with expected name + GITHUB_OUTPUT written ──


def test_happy_path_creates_backup_with_expected_name(capsys, monkeypatch):
    runner = FakeRunner(
        {
            "cluster-info": _completed(),
            "get deployment velero": _completed(),
            "velero backup create": _completed(),
            "jsonpath={.status.phase}": _completed(stdout="Completed"),
        }
    )
    monkeypatch.setattr(backup.subprocess, "run", runner)
    monkeypatch.setattr(backup.shutil, "which", lambda _x: "/usr/local/bin/velero")
    rc = backup.main(["--git-sha", "abc1234"])
    assert rc == 0
    create_call = next(
        c for c in runner.calls if "velero" in c and "backup" in c and "create" in c
    )
    # Expected pattern: velero backup create pre-deploy-<sha>-<ts> ...
    name = create_call[3]
    assert name.startswith("pre-deploy-abc1234-")
    assert name.split("-")[-1].isdigit()


def test_happy_path_writes_github_output(monkeypatch, tmp_path):
    output_file = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    runner = FakeRunner(
        {
            "cluster-info": _completed(),
            "get deployment velero": _completed(),
            "velero backup create": _completed(),
            "jsonpath={.status.phase}": _completed(stdout="Completed"),
        }
    )
    monkeypatch.setattr(backup.subprocess, "run", runner)
    monkeypatch.setattr(backup.shutil, "which", lambda _x: "/usr/local/bin/velero")
    backup.main(["--git-sha", "abc1234"])
    contents = output_file.read_text()
    assert "BACKUP_NAME=pre-deploy-abc1234-" in contents


# ── failure modes inside the happy path ────────────────────────────────────


def test_failure_when_velero_create_returns_nonzero(monkeypatch):
    runner = FakeRunner(
        {
            "cluster-info": _completed(),
            "get deployment velero": _completed(),
            "velero backup create": subprocess.CalledProcessError(
                returncode=2, cmd=["velero", "backup", "create"]
            ),
        }
    )
    monkeypatch.setattr(backup.subprocess, "run", runner)
    monkeypatch.setattr(backup.shutil, "which", lambda _x: "/usr/local/bin/velero")
    assert backup.main(["--git-sha", "abc1234"]) == 1


def test_failure_when_phase_not_completed(monkeypatch):
    runner = FakeRunner(
        {
            "cluster-info": _completed(),
            "get deployment velero": _completed(),
            "velero backup create": _completed(),
            "jsonpath={.status.phase}": _completed(stdout="Failed"),
        }
    )
    monkeypatch.setattr(backup.subprocess, "run", runner)
    monkeypatch.setattr(backup.shutil, "which", lambda _x: "/usr/local/bin/velero")
    assert backup.main(["--git-sha", "abc1234"]) == 1


# ── pure helpers ───────────────────────────────────────────────────────────


def test_default_git_sha_returns_unknown_on_error(monkeypatch):
    monkeypatch.setattr(
        backup.subprocess, "run", lambda *a, **kw: _completed(returncode=1)
    )
    assert backup.default_git_sha() == "unknown"


def test_write_github_output_silent_no_op_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    # Should not raise.
    backup.write_github_output("KEY", "value")
