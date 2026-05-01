"""Tests for infra/aws/scripts/clean_lab.py"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "infra" / "aws" / "scripts")
)

import clean_lab  # noqa: E402


VALID_IDENTITY = {
    "UserId": "AIDAIOSFODNN7EXAMPLE",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/alice",
}


def _identity_stdout(identity):
    mock = MagicMock()
    mock.stdout = json.dumps(identity)
    mock.returncode = 0
    return mock


# ── get_caller_identity ──────────────────────────────────────────────────────


def test_get_caller_identity_parses_account_and_arn():
    with patch(
        "clean_lab.subprocess.run", return_value=_identity_stdout(VALID_IDENTITY)
    ):
        account, arn = clean_lab.get_caller_identity()
    assert account == "123456789012"
    assert arn == "arn:aws:iam::123456789012:user/alice"


def test_get_caller_identity_invokes_aws_sts_with_check_true():
    with patch(
        "clean_lab.subprocess.run", return_value=_identity_stdout(VALID_IDENTITY)
    ) as mock_run:
        clean_lab.get_caller_identity()
    args, kwargs = mock_run.call_args
    assert args[0] == ["aws", "sts", "get-caller-identity", "--output", "json"]
    assert kwargs.get("check") is True
    assert kwargs.get("capture_output") is True
    assert kwargs.get("text") is True


def test_get_caller_identity_raises_on_subprocess_failure():
    failure = subprocess.CalledProcessError(returncode=255, cmd=["aws"])
    with patch("clean_lab.subprocess.run", side_effect=failure):
        try:
            clean_lab.get_caller_identity()
        except subprocess.CalledProcessError:
            return
    raise AssertionError("expected CalledProcessError")


def test_get_caller_identity_raises_on_invalid_json():
    bad = MagicMock()
    bad.stdout = "not-json"
    with patch("clean_lab.subprocess.run", return_value=bad):
        try:
            clean_lab.get_caller_identity()
        except json.JSONDecodeError:
            return
    raise AssertionError("expected JSONDecodeError")


# ── countdown ────────────────────────────────────────────────────────────────


def test_countdown_sleeps_once_per_second(capsys):
    with patch("clean_lab.time.sleep") as mock_sleep:
        clean_lab.countdown(3)
    assert mock_sleep.call_count == 3
    mock_sleep.assert_has_calls([call(1), call(1), call(1)])
    out = capsys.readouterr().out
    assert "3... " in out
    assert "2... " in out
    assert "1... " in out
    assert "GO!" in out


def test_countdown_zero_seconds_only_prints_go(capsys):
    with patch("clean_lab.time.sleep") as mock_sleep:
        clean_lab.countdown(0)
    assert mock_sleep.call_count == 0
    assert "GO!" in capsys.readouterr().out


# ── run_nuke_loop ────────────────────────────────────────────────────────────


def test_run_nuke_loop_executes_exact_attempts():
    with patch("clean_lab.subprocess.run") as mock_run, patch("clean_lab.time.sleep"):
        clean_lab.run_nuke_loop(attempts=3)
    assert mock_run.call_count == 3


def test_run_nuke_loop_sleeps_between_but_not_after_last():
    with patch("clean_lab.subprocess.run"), patch("clean_lab.time.sleep") as mock_sleep:
        clean_lab.run_nuke_loop(attempts=5)
    assert mock_sleep.call_count == 4
    mock_sleep.assert_has_calls([call(clean_lab.NUKE_DELAY_SECONDS)] * 4)


def test_run_nuke_loop_single_attempt_skips_sleep():
    with patch("clean_lab.subprocess.run"), patch("clean_lab.time.sleep") as mock_sleep:
        clean_lab.run_nuke_loop(attempts=1)
    assert mock_sleep.call_count == 0


def test_run_nuke_loop_passes_nuke_arguments_verbatim():
    with patch("clean_lab.subprocess.run") as mock_run, patch("clean_lab.time.sleep"):
        clean_lab.run_nuke_loop(attempts=1)
    mock_run.assert_called_once_with(
        [
            "aws-nuke",
            "run",
            "--config",
            "config.yml",
            "--profile",
            "default",
            "--no-dry-run",
            "--force",
        ],
        check=True,
    )


def test_run_nuke_loop_default_uses_total_attempts_constant():
    with patch("clean_lab.subprocess.run") as mock_run, patch("clean_lab.time.sleep"):
        clean_lab.run_nuke_loop()
    assert mock_run.call_count == clean_lab.TOTAL_ATTEMPTS


# ── main (confirmation + full flow) ──────────────────────────────────────────


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch("clean_lab.get_caller_identity", return_value=("123", "arn:x"))
def test_main_returns_1_when_confirmation_mismatches(
    _identity, mock_countdown, mock_loop, capsys
):
    with patch("builtins.input", return_value="nope"):
        rc = clean_lab.main()
    assert rc == 1
    mock_loop.assert_not_called()
    mock_countdown.assert_not_called()
    assert "cancelada" in capsys.readouterr().out.lower()


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch("clean_lab.get_caller_identity", return_value=("123", "arn:x"))
def test_main_returns_1_on_empty_confirmation(_identity, _cd, mock_loop):
    with patch("builtins.input", return_value=""):
        rc = clean_lab.main()
    assert rc == 1
    mock_loop.assert_not_called()


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch("clean_lab.get_caller_identity", return_value=("123", "arn:x"))
def test_main_requires_exact_uppercase_sim(_identity, _cd, mock_loop):
    # Lowercase "sim" must not proceed — confirmation token is case-sensitive.
    with patch("builtins.input", return_value="sim"):
        rc = clean_lab.main()
    assert rc == 1
    mock_loop.assert_not_called()


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch("clean_lab.get_caller_identity", return_value=("999", "arn:y"))
def test_main_proceeds_when_confirmed(_identity, mock_countdown, mock_loop, capsys):
    with patch("builtins.input", return_value="SIM"):
        rc = clean_lab.main()
    assert rc == 0
    mock_countdown.assert_called_once_with(clean_lab.COUNTDOWN_SECONDS)
    mock_loop.assert_called_once_with()
    assert "finalizado" in capsys.readouterr().out.lower()


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch(
    "clean_lab.get_caller_identity",
    return_value=("123456789012", "arn:aws:iam::123456789012:user/alice"),
)
def test_main_displays_account_and_arn(_identity, _cd, _loop, capsys):
    with patch("builtins.input", return_value="SIM"):
        clean_lab.main()
    out = capsys.readouterr().out
    assert "123456789012" in out
    assert "arn:aws:iam::123456789012:user/alice" in out


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch("clean_lab.get_caller_identity", return_value=("1", "a"))
def test_main_prints_protocol_banner(_identity, _cd, _loop, capsys):
    with patch("builtins.input", return_value="SIM"):
        clean_lab.main()
    out = capsys.readouterr().out
    assert "PROTOCOLO DE DESTRUIÇÃO" in out
    assert f"aws-nuke {clean_lab.TOTAL_ATTEMPTS} VEZES" in out


@patch("clean_lab.run_nuke_loop")
@patch("clean_lab.countdown")
@patch(
    "clean_lab.get_caller_identity",
    side_effect=subprocess.CalledProcessError(returncode=253, cmd=["aws"]),
)
def test_main_falls_back_to_unknown_on_aws_sts_failure(_identity, _cd, _loop, capsys):
    """Matches original shell semantics — STS failure must not crash with a traceback."""
    with patch("builtins.input", return_value="nope"):
        rc = clean_lab.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "unknown" in out
