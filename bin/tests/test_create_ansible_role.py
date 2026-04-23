"""Tests for bin/create_ansible_role.py"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import create_ansible_role as car  # noqa: E402


def _build_fake_template(base_dir):
    """Create a minimal .template dir mimicking the real Ansible scaffold."""
    template = base_dir / "ansible" / "roles" / ".template"
    (template / "meta").mkdir(parents=True)
    (template / "defaults").mkdir()
    (template / "tasks").mkdir()
    (template / "molecule" / "default").mkdir(parents=True)

    (template / "meta" / "main.yml").write_text("role_name: [ROLE_NAME]\n")
    (template / "README.md").write_text("# [ROLE_NAME]\n")
    (template / "defaults" / "main.yml").write_text("---\n")
    (template / "tasks" / "main.yml").write_text("---\n# [ROLE_NAME] tasks\n")
    (template / "molecule" / "default" / "molecule.yml").write_text(
        "role: [ROLE_NAME]\n"
    )
    (template / "molecule" / "default" / "converge.yml").write_text(
        "- include_role: [ROLE_NAME]\n"
    )
    (template / "molecule" / "default" / "verify.yml").write_text(
        "# verify [ROLE_NAME]\n"
    )
    return template


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


# ── create_role ──────────────────────────────────────────────────────────────


def test_create_role_rejects_empty_name(tmp_path, capsys):
    rc = car.create_role("", base_dir=tmp_path)
    assert rc == 1
    assert "Usage" in capsys.readouterr().err


def test_create_role_rejects_invalid_name(tmp_path, capsys):
    _build_fake_template(tmp_path)
    rc = car.create_role("foo-bar", base_dir=tmp_path)
    assert rc == 1
    err = capsys.readouterr().err
    assert "Invalid role name" in err
    assert "alphanumeric characters and underscores" in err


def test_create_role_fails_if_target_already_exists(tmp_path, capsys):
    _build_fake_template(tmp_path)
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


def test_create_role_copies_full_structure(tmp_path):
    _build_fake_template(tmp_path)
    rc = car.create_role("my_role", base_dir=tmp_path)
    assert rc == 0

    role = tmp_path / "ansible" / "roles" / "my_role"
    assert (role / "meta" / "main.yml").is_file()
    assert (role / "defaults" / "main.yml").is_file()
    assert (role / "tasks" / "main.yml").is_file()
    assert (role / "molecule" / "default" / "molecule.yml").is_file()
    assert (role / "molecule" / "default" / "converge.yml").is_file()
    assert (role / "molecule" / "default" / "verify.yml").is_file()
    assert (role / "README.md").is_file()


def test_create_role_substitutes_placeholder_in_listed_files(tmp_path):
    _build_fake_template(tmp_path)
    car.create_role("my_role", base_dir=tmp_path)
    role = tmp_path / "ansible" / "roles" / "my_role"

    assert "my_role" in (role / "meta" / "main.yml").read_text()
    assert "my_role" in (role / "README.md").read_text()
    assert "my_role" in (role / "molecule" / "default" / "molecule.yml").read_text()
    assert "my_role" in (role / "molecule" / "default" / "converge.yml").read_text()
    assert "my_role" in (role / "molecule" / "default" / "verify.yml").read_text()
    for rel in car.PLACEHOLDER_FILES:
        assert car.PLACEHOLDER not in (role / rel).read_text()


def test_create_role_leaves_non_listed_files_untouched(tmp_path):
    """tasks/main.yml is not in PLACEHOLDER_FILES — its placeholder stays."""
    _build_fake_template(tmp_path)
    car.create_role("my_role", base_dir=tmp_path)
    role = tmp_path / "ansible" / "roles" / "my_role"
    # tasks/main.yml is NOT in the substitution list; placeholder must remain
    assert car.PLACEHOLDER in (role / "tasks" / "main.yml").read_text()


def test_create_role_prints_next_steps(tmp_path, capsys):
    _build_fake_template(tmp_path)
    car.create_role("my_role", base_dir=tmp_path)
    out = capsys.readouterr().out
    assert "Role created successfully" in out
    assert "make test-molecule-my_role" in out
    assert "make validate-ansible-structure" in out
    assert "CONTRIBUTING.md" in out


def test_create_role_handles_missing_placeholder_file_gracefully(tmp_path):
    """If a placeholder file is missing from template, skip silently (shell parity)."""
    template = _build_fake_template(tmp_path)
    (template / "README.md").unlink()  # remove one of the listed files

    rc = car.create_role("my_role", base_dir=tmp_path)
    assert rc == 0
    role = tmp_path / "ansible" / "roles" / "my_role"
    assert not (role / "README.md").exists()


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
