"""Tests for bin/ssm_activation_bootstrap.py — TF output extraction → sops set."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ssm_activation_bootstrap as boot  # noqa: E402


def test_get_terraform_output_strips_value():
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="mi-abc\n", stderr="")
    with patch.object(boot.subprocess, "run", return_value=completed):
        assert boot.get_terraform_output("ssm_activation_id", Path("infra/aws-velero")) == "mi-abc"


def test_get_terraform_output_raises_on_empty():
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="  \n", stderr="")
    with patch.object(boot.subprocess, "run", return_value=completed):
        with pytest.raises(RuntimeError):
            boot.get_terraform_output("ssm_activation_id", Path("infra/aws-velero"))


def test_get_terraform_output_raises_on_nonzero():
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with patch.object(boot.subprocess, "run", return_value=completed):
        with pytest.raises(RuntimeError):
            boot.get_terraform_output("missing", Path("infra/aws-velero"))


def test_bootstrap_sets_both_keys_via_sops():
    outputs = {"ssm_activation_id": "mi-123", "ssm_activation_code": "code-xyz"}
    sets: list[tuple[str, str]] = []

    with patch.object(boot, "get_terraform_output", side_effect=lambda name, _: outputs[name]), patch.object(
        boot, "sops_set", side_effect=lambda _path, key, value: sets.append((key, value))
    ):
        boot.bootstrap(Path("infra/aws-velero"), Path("ansible/group_vars/all.sops.yml"))

    assert sets == [
        ("ssm_activation_id", "mi-123"),
        ("ssm_activation_code", "code-xyz"),
    ]


def test_sops_set_invokes_sops_with_json_value():
    with patch.object(boot.subprocess, "run") as mock_run:
        boot.sops_set(Path("vars.sops.yml"), "ssm_activation_id", "mi-123")
    args = mock_run.call_args[0][0]
    assert args[:3] == ["sops", "set", "vars.sops.yml"]
    assert args[3] == '["ssm_activation_id"]'
    assert args[4] == '"mi-123"'


def test_main_returns_one_on_failure(capsys):
    with patch.object(boot, "bootstrap", side_effect=RuntimeError("nope")):
        rc = boot.main([])
    assert rc == 1
    assert "nope" in capsys.readouterr().err


def test_main_returns_zero_on_success():
    with patch.object(boot, "bootstrap"):
        assert boot.main([]) == 0
