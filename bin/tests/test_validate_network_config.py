"""Tests for ansible/scripts/validate_network_config.py"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ansible" / "scripts"))

import validate_network_config as vnc  # noqa: E402


def _build_valid_ansible_root(tmp_path):
    """Create a fake ansible root with all six checks in passing state."""
    (tmp_path / "inventory").mkdir()
    (tmp_path / "group_vars").mkdir()
    (tmp_path / "roles" / "gatekeeper" / "tasks").mkdir(parents=True)
    (tmp_path / "playbooks").mkdir()

    (tmp_path / "inventory" / "production.yml").write_text(
        "\n".join(vnc.INVENTORY_IPS) + "\n"
    )
    (tmp_path / "group_vars" / "all.yml").write_text(
        "\n".join(vnc.GROUP_VARS_MARKERS) + "\n"
    )
    (tmp_path / "roles" / "gatekeeper" / "tasks" / "main.yml").write_text(
        "\n".join(vnc.ZERO_TRUST_MARKERS + vnc.WAN_DHCP_MARKERS) + "\n"
    )
    (tmp_path / "playbooks" / "configure_router.yml").write_text(
        "- hosts: routers\n  tasks: []\n"
    )
    return tmp_path


# ── file_contains_all ────────────────────────────────────────────────────────


def test_file_contains_all_true_when_all_present(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("alpha\nbravo\ncharlie\n")
    assert vnc.file_contains_all(f, ["alpha", "charlie"]) is True


def test_file_contains_all_false_when_one_missing(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("alpha\nbravo\n")
    assert vnc.file_contains_all(f, ["alpha", "delta"]) is False


def test_file_contains_all_false_when_file_missing(tmp_path):
    assert vnc.file_contains_all(tmp_path / "missing.txt", ["x"]) is False


# ── validate: full-pass baseline ─────────────────────────────────────────────


def test_validate_all_pass_no_ansible(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 0
    out = capsys.readouterr().out
    assert "Ansible not installed" in out


# ── validate: each failure branch ────────────────────────────────────────────


def test_validate_fails_on_missing_inventory_ips(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    (root / "inventory" / "production.yml").write_text("# empty\n")
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 1
    assert "Missing or incorrect IP addresses" in capsys.readouterr().out


def test_validate_fails_on_missing_group_vars(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    (root / "group_vars" / "all.yml").write_text("# empty\n")
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 1
    assert "Missing or incorrect network topology variables" in capsys.readouterr().out


def test_validate_fails_on_missing_zero_trust_rule(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    (root / "roles" / "gatekeeper" / "tasks" / "main.yml").write_text(
        "\n".join(vnc.WAN_DHCP_MARKERS) + "\n"
    )
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 1
    assert "Zero Trust isolation rule missing" in capsys.readouterr().out


def test_validate_fails_on_missing_wan_dhcp(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    (root / "roles" / "gatekeeper" / "tasks" / "main.yml").write_text(
        "\n".join(vnc.ZERO_TRUST_MARKERS) + "\n"
    )
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 1
    assert "WAN DHCP configuration missing" in capsys.readouterr().out


def test_validate_fails_on_missing_router_playbook(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    (root / "playbooks" / "configure_router.yml").unlink()
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 1
    assert "Router playbook missing" in capsys.readouterr().out


def test_validate_counts_multiple_failures_independently(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    (root / "inventory" / "production.yml").write_text("")
    (root / "group_vars" / "all.yml").write_text("")
    (root / "playbooks" / "configure_router.yml").unlink()
    with patch("validate_network_config.shutil.which", return_value=None):
        errors = vnc.validate(root)
    assert errors == 3


# ── validate: ansible-playbook branch ────────────────────────────────────────


def test_validate_runs_syntax_check_when_ansible_available(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    with patch(
        "validate_network_config.shutil.which", return_value="/usr/bin/ansible-playbook"
    ), patch("validate_network_config.subprocess.run") as mock_run:
        errors = vnc.validate(root)
    assert errors == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "ansible-playbook"
    assert cmd[1] == "--syntax-check"
    assert "Ansible playbook syntax valid" in capsys.readouterr().out


def test_validate_marks_syntax_check_failure(tmp_path, capsys):
    root = _build_valid_ansible_root(tmp_path)
    failure = subprocess.CalledProcessError(returncode=2, cmd=["ansible-playbook"])
    with patch(
        "validate_network_config.shutil.which", return_value="/usr/bin/ansible-playbook"
    ), patch("validate_network_config.subprocess.run", side_effect=failure):
        errors = vnc.validate(root)
    assert errors == 1
    assert "Ansible playbook has syntax errors" in capsys.readouterr().out


# ── main ─────────────────────────────────────────────────────────────────────


def test_main_returns_0_when_validate_clean():
    with patch("validate_network_config.validate", return_value=0):
        rc = vnc.main()
    assert rc == 0


def test_main_returns_1_when_validate_reports_errors(capsys):
    with patch("validate_network_config.validate", return_value=3):
        rc = vnc.main()
    assert rc == 1
    out = capsys.readouterr().out
    assert "Validation failed with 3 error(s)" in out


def test_main_prints_next_steps_on_success(capsys):
    with patch("validate_network_config.validate", return_value=0):
        vnc.main()
    out = capsys.readouterr().out
    assert "All validation checks passed" in out
    assert "ansible-playbook -i inventory/production.yml" in out


def test_main_prints_banner():
    with patch("validate_network_config.validate", return_value=0):
        vnc.main()
