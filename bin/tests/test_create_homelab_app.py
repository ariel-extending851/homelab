"""Tests for bin/create_homelab_app.py (Copier-based k8s-app scaffolder)."""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import create_homelab_app as cha  # noqa: E402


# ── validate_app_name ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("adguard", True),
        ("kube-state-metrics", True),
        ("hl-monitoring", True),
        ("a", True),
        ("a1", True),
        # Reject: leading digit, uppercase, underscores, empty, special chars.
        ("9app", False),
        ("My-App", False),
        ("my_app", False),
        ("", False),
        (".hidden", False),
        ("my.app", False),
        ("my app", False),
    ],
)
def test_validate_app_name(name, expected):
    assert cha.validate_app_name(name) is expected


# ── create_app: validation paths ─────────────────────────────────────────────


def test_create_app_rejects_empty_name(tmp_path, capsys):
    rc = cha.create_app("", base_dir=tmp_path)
    assert rc == 1
    assert "Usage" in capsys.readouterr().err


def test_create_app_rejects_invalid_name(tmp_path, capsys):
    (tmp_path / cha.TEMPLATE_SUBPATH).mkdir(parents=True)
    rc = cha.create_app("Bad_Name", base_dir=tmp_path)
    assert rc == 1
    assert "kebab-case" in capsys.readouterr().err


def test_create_app_fails_if_target_exists(tmp_path, capsys):
    (tmp_path / cha.TEMPLATE_SUBPATH).mkdir(parents=True)
    existing = tmp_path / cha.APPS_SUBPATH / "myapp"
    existing.mkdir(parents=True)
    rc = cha.create_app("myapp", base_dir=tmp_path)
    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def test_create_app_fails_if_template_missing(tmp_path, capsys):
    rc = cha.create_app("myapp", base_dir=tmp_path)
    assert rc == 1
    assert "Template not found" in capsys.readouterr().err


def test_create_app_fails_if_copier_missing(tmp_path, capsys):
    (tmp_path / cha.TEMPLATE_SUBPATH).mkdir(parents=True)
    with patch("create_homelab_app._resolve_copier", return_value=None):
        rc = cha.create_app("myapp", base_dir=tmp_path)
    assert rc == 2
    assert "copier" in capsys.readouterr().err.lower()


# ── create_app: happy path ───────────────────────────────────────────────────


def test_create_app_invokes_copier_with_expected_args(tmp_path, capsys):
    (tmp_path / cha.TEMPLATE_SUBPATH).mkdir(parents=True)
    (tmp_path / cha.APPS_SUBPATH).mkdir(parents=True)
    (tmp_path / cha.ROOT_KUSTOMIZATION).write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\nresources:\n- ./prometheus\n"
    )
    captured = {}

    def fake_run(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return types.SimpleNamespace(returncode=0)

    with patch("create_homelab_app.subprocess.run", side_effect=fake_run):
        rc = cha.create_app("myapp", base_dir=tmp_path, copier_runner=["copier"])

    assert rc == 0
    cmd = captured["cmd"]
    assert "copy" in cmd
    assert "app_name=myapp" in cmd
    # `today` is auto-set; just confirm the key is supplied.
    assert any(c.startswith("today=") for c in cmd)
    assert str(tmp_path / cha.TEMPLATE_SUBPATH) in cmd
    assert str(tmp_path / cha.APPS_SUBPATH / "myapp") in cmd

    # Side-effect: registered in root kustomization
    root_text = (tmp_path / cha.ROOT_KUSTOMIZATION).read_text()
    assert "- ./myapp" in root_text

    out = capsys.readouterr().out
    assert "App created successfully" in out
    assert "make generate-catalog" in out


def test_register_in_root_kustomization_is_idempotent(tmp_path):
    (tmp_path / cha.APPS_SUBPATH).mkdir(parents=True)
    root = tmp_path / cha.ROOT_KUSTOMIZATION
    root.write_text("resources:\n- ./myapp\n")

    cha.register_in_root_kustomization(tmp_path, "myapp")
    # Should not append a duplicate entry.
    assert root.read_text().count("- ./myapp") == 1


def test_register_in_root_kustomization_warns_if_missing(tmp_path, capsys):
    cha.register_in_root_kustomization(tmp_path, "myapp")
    assert "register the app manually" in capsys.readouterr().err


def test_create_app_propagates_copier_failure(tmp_path, capsys):
    (tmp_path / cha.TEMPLATE_SUBPATH).mkdir(parents=True)

    def fake_run(cmd, cwd=None):  # noqa: ARG001
        return types.SimpleNamespace(returncode=99)

    with patch("create_homelab_app.subprocess.run", side_effect=fake_run):
        rc = cha.create_app("myapp", base_dir=tmp_path, copier_runner=["copier"])
    assert rc == 99
    assert "copier failed" in capsys.readouterr().err


# ── main entry point ─────────────────────────────────────────────────────────


def test_main_no_args_returns_1(capsys):
    rc = cha.main([])
    assert rc == 1
    assert "Usage" in capsys.readouterr().err


def test_main_delegates_to_create_app_with_cwd():
    with patch("create_homelab_app.create_app", return_value=0) as mock_create:
        rc = cha.main(["my-app"])
    assert rc == 0
    mock_create.assert_called_once()
    assert mock_create.call_args.args[0] == "my-app"
    assert mock_create.call_args.kwargs["base_dir"] == Path.cwd()
