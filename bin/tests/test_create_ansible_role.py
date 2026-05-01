"""Tests for bin/create_ansible_role.py (Copier-wrapper edition).

The script no longer performs string substitution itself — it delegates to
`copier copy templates/ansible-role/`. These tests cover:
  - role-name validation (regex contract preserved from the old shell script)
  - error paths: missing template dir, target already exists, copier missing
  - the happy path that calls copier with the expected args
"""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import create_ansible_role as car  # noqa: E402


# ── validate_role_name ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("foo", True),
        ("Foo", True),
        ("foo_bar", True),
        ("foo123", True),
        ("FOO_BAR_42", True),
        ("_underscore_first", True),
        ("9", True),
        ("foo-bar", False),
        ("foo bar", False),
        ("foo.bar", False),
        ("foo/bar", False),
        ("", False),
        ("../evil", False),
        ("foo\nbar", False),
    ],
)
def test_validate_role_name(name, expected):
    assert car.validate_role_name(name) is expected


# ── create_role: validation paths ────────────────────────────────────────────


def test_create_role_rejects_empty_name(tmp_path, capsys):
    rc = car.create_role("", base_dir=tmp_path)
    assert rc == 1
    assert "Usage" in capsys.readouterr().err


def test_create_role_rejects_invalid_name(tmp_path, capsys):
    (tmp_path / car.TEMPLATE_SUBPATH).mkdir(parents=True)
    rc = car.create_role("foo-bar", base_dir=tmp_path)
    assert rc == 1
    err = capsys.readouterr().err
    assert "Invalid role name" in err
    assert "alphanumeric characters and underscores" in err


def test_create_role_fails_if_target_already_exists(tmp_path, capsys):
    (tmp_path / car.TEMPLATE_SUBPATH).mkdir(parents=True)
    existing = tmp_path / "ansible" / "roles" / "existing_role"
    existing.mkdir(parents=True)

    rc = car.create_role("existing_role", base_dir=tmp_path)
    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def test_create_role_fails_if_template_missing(tmp_path, capsys):
    rc = car.create_role("my_role", base_dir=tmp_path)
    assert rc == 1
    err = capsys.readouterr().err
    assert "Template not found" in err
    assert "repository root" in err


def test_create_role_fails_if_copier_missing(tmp_path, capsys):
    (tmp_path / car.TEMPLATE_SUBPATH).mkdir(parents=True)
    with patch("create_ansible_role._resolve_copier", return_value=None):
        rc = car.create_role("my_role", base_dir=tmp_path)
    assert rc == 2
    assert "copier" in capsys.readouterr().err.lower()


# ── create_role: happy path ──────────────────────────────────────────────────


def _fake_run(returncode=0):
    def runner(cmd, cwd=None):  # noqa: ARG001
        return types.SimpleNamespace(returncode=returncode)

    return runner


def test_create_role_invokes_copier_with_expected_args(tmp_path, capsys):
    (tmp_path / car.TEMPLATE_SUBPATH).mkdir(parents=True)
    captured = {}

    def fake_run(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return types.SimpleNamespace(returncode=0)

    with patch("create_ansible_role.subprocess.run", side_effect=fake_run):
        rc = car.create_role("my_role", base_dir=tmp_path, copier_runner=["copier"])

    assert rc == 0
    assert captured["cmd"][0] == "copier"
    assert "copy" in captured["cmd"]
    assert "--defaults" in captured["cmd"]
    assert "role_name=my_role" in captured["cmd"]
    # Both source-template and dest-role-dir are present as positional args.
    assert str(tmp_path / car.TEMPLATE_SUBPATH) in captured["cmd"]
    assert str(tmp_path / "ansible" / "roles" / "my_role") in captured["cmd"]
    assert captured["cwd"] == tmp_path

    out = capsys.readouterr().out
    assert "Role created successfully" in out
    assert "make test-molecule-my_role" in out
    assert "make validate-ansible-structure" in out
    assert "CONTRIBUTING.md" in out


def test_create_role_propagates_copier_failure(tmp_path, capsys):
    (tmp_path / car.TEMPLATE_SUBPATH).mkdir(parents=True)
    with patch(
        "create_ansible_role.subprocess.run", side_effect=_fake_run(returncode=42)
    ):
        rc = car.create_role("my_role", base_dir=tmp_path, copier_runner=["copier"])
    assert rc == 42
    assert "copier failed" in capsys.readouterr().err


# ── _resolve_copier ──────────────────────────────────────────────────────────


def test_resolve_copier_prefers_path_binary():
    with patch(
        "create_ansible_role.shutil.which",
        side_effect=lambda b: f"/usr/bin/{b}" if b == "copier" else None,
    ):
        assert car._resolve_copier() == "/usr/bin/copier"


def test_resolve_copier_falls_back_to_mise():
    def fake_which(b):
        return "/usr/bin/mise" if b == "mise" else None

    with patch("create_ansible_role.shutil.which", side_effect=fake_which):
        assert car._resolve_copier() == ["mise", "exec", "--", "copier"]


def test_resolve_copier_returns_none_when_unavailable():
    with patch("create_ansible_role.shutil.which", return_value=None):
        assert car._resolve_copier() is None


# ── main entry point ─────────────────────────────────────────────────────────


def test_main_no_args_returns_1(capsys):
    rc = car.main([])
    assert rc == 1
    assert "Usage" in capsys.readouterr().err


def test_main_delegates_to_create_role_with_cwd():
    with patch("create_ansible_role.create_role", return_value=0) as mock_create:
        rc = car.main(["my_role"])
    assert rc == 0
    mock_create.assert_called_once()
    role_name_arg = mock_create.call_args.args[0]
    base_dir_arg = mock_create.call_args.kwargs["base_dir"]
    assert role_name_arg == "my_role"
    assert base_dir_arg == Path.cwd()


def test_main_propagates_nonzero_from_create_role():
    with patch("create_ansible_role.create_role", return_value=1):
        rc = car.main(["bad"])
    assert rc == 1
