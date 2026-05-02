"""Orchestration error-path tests for bin/deploy_aws_homelab.py.

Complements test_deploy_aws_homelab.py (which covers individual functions
and happy-path stage ordering) with parameterized failure scenarios:
each stage fails in turn, and the test asserts:

  1. main() propagates a non-zero exit code (SystemExit).
  2. The state file contains every stage BEFORE the failure but NOT
     the failing stage or later ones — proving --resume-from will
     correctly resume from where things broke.
  3. Stages AFTER the failing one are never invoked.

All AWS / kubectl / ansible / terraform calls are mocked. No real
infrastructure is touched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deploy_aws_homelab as deploy  # noqa: E402


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Isolate the deploy state file to a temp path per test."""
    path = tmp_path / "deploy-state.json"
    monkeypatch.setenv("HOMELAB_DEPLOY_STATE_FILE", str(path))
    return path


@pytest.fixture
def recorded_stages(monkeypatch):
    """Replace each stage with a recorder that can be told to fail.

    Returns ``(calls, set_failure)`` — calls is the list of stage names
    actually invoked; set_failure(name) makes the named stage raise
    SystemExit(1) when called (mimicking error_exit).
    """
    calls: list[str] = []
    fail_at: dict[str, bool] = {}

    def make(name):
        def runner(_config):
            calls.append(name)
            if fail_at.get(name):
                # Same shape as error_exit() — exit code 1.
                raise SystemExit(1)

        return runner

    monkeypatch.setattr(deploy, "check_prerequisites", make("prerequisites"))
    monkeypatch.setattr(deploy, "phase1_terraform", make("terraform"))
    monkeypatch.setattr(deploy, "phase2_wait_for_instances", make("instances"))
    monkeypatch.setattr(deploy, "phase2_5_wait_for_tailscale", make("tailscale"))
    monkeypatch.setattr(deploy, "phase3_ansible", make("ansible"))
    monkeypatch.setattr(deploy, "phase4_verify", make("verify"))
    monkeypatch.setattr(deploy, "print_banner", lambda: None)
    monkeypatch.setattr(deploy, "print_summary", lambda _c: None)

    def set_failure(name):
        fail_at[name] = True

    return calls, set_failure


# ── parameterized: each stage fails → assert state and side effects ─────────


@pytest.mark.parametrize(
    "failing_stage,stages_that_should_run,stages_that_should_not_run",
    [
        (
            "prerequisites",
            ["prerequisites"],
            ["terraform", "instances", "tailscale", "ansible", "verify"],
        ),
        (
            "terraform",
            ["prerequisites", "terraform"],
            ["instances", "tailscale", "ansible", "verify"],
        ),
        (
            "instances",
            ["prerequisites", "terraform", "instances"],
            ["tailscale", "ansible", "verify"],
        ),
        (
            "tailscale",
            ["prerequisites", "terraform", "instances", "tailscale"],
            ["ansible", "verify"],
        ),
        (
            "ansible",
            ["prerequisites", "terraform", "instances", "tailscale", "ansible"],
            ["verify"],
        ),
    ],
)
def test_failure_at_each_stage_propagates_and_records_state(
    state_file,
    recorded_stages,
    failing_stage,
    stages_that_should_run,
    stages_that_should_not_run,
):
    calls, set_failure = recorded_stages
    set_failure(failing_stage)

    with pytest.raises(SystemExit) as exc:
        deploy.main([])
    assert exc.value.code == 1

    # Stages run, in order, up to and including the failing one.
    assert calls == stages_that_should_run

    # State file records only the stages that COMPLETED — not the failing one.
    saved = json.loads(state_file.read_text()) if state_file.exists() else {}
    completed = set(saved.keys())
    expected_completed = set(stages_that_should_run) - {failing_stage}
    assert completed == expected_completed

    # And of course, no post-failure stages were called.
    for stage in stages_that_should_not_run:
        assert stage not in calls


def test_resume_after_terraform_failure_skips_completed_prerequisites(
    state_file, recorded_stages
):
    """Round-trip: fail at terraform → state has only 'prerequisites' →
    second run with --resume-from=terraform skips prerequisites and
    re-runs terraform onwards."""
    calls, set_failure = recorded_stages
    set_failure("terraform")

    # First run fails at terraform.
    with pytest.raises(SystemExit):
        deploy.main([])
    saved = json.loads(state_file.read_text())
    assert list(saved.keys()) == ["prerequisites"]

    # Reset failure, second run with --resume-from=terraform.
    calls.clear()
    set_failure("terraform")  # still fails — verify resume tries it again
    with pytest.raises(SystemExit):
        deploy.main(["--resume-from", "terraform"])
    # Prerequisites was fresh in state → skipped on resume.
    assert "prerequisites" not in calls
    assert "terraform" in calls


def test_clean_state_after_full_success(state_file, recorded_stages):
    """All 6 stages should appear in state after a successful end-to-end run."""
    calls, _ = recorded_stages
    assert deploy.main([]) == 0
    saved = json.loads(state_file.read_text())
    assert set(saved.keys()) == set(deploy.STAGES)
    # Timestamps are in monotonically non-decreasing order
    timestamps = [saved[s] for s in deploy.STAGES]
    assert timestamps == sorted(timestamps)


def test_state_records_unix_timestamp_within_recent_window(state_file, recorded_stages):
    """Sanity check: the timestamp written is current unix time (±5s)."""
    deploy.main([])
    saved = json.loads(state_file.read_text())
    now = int(time.time())
    for stage, ts in saved.items():
        assert isinstance(ts, int), f"{stage} ts is not int: {ts!r}"
        assert abs(now - ts) < 5, f"{stage} ts {ts} not near now {now}"


def test_destroy_path_does_not_touch_state_file(state_file, monkeypatch):
    """`--destroy` runs destroy_infrastructure and never enters the
    stages_plan loop, so it must not write to the state file."""
    monkeypatch.setattr(deploy, "destroy_infrastructure", lambda _c: None)
    monkeypatch.setattr(deploy, "print_banner", lambda: None)
    assert deploy.main(["--destroy"]) == 0
    assert not state_file.exists()
