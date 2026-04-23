"""Tests for bin/deploy_aws_homelab.py

Ports every case from the removed bin/tests/deploy_functions.bats to
pytest, plus extra coverage for the orchestrator, argparse, and the
destroy confirmation flow.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deploy_aws_homelab as deploy  # noqa: E402


# ── helpers ─────────────────────────────────────────────────────────────────


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _config(env=None):
    return deploy.DeployConfig(env=env or {})


# ── logging helpers ─────────────────────────────────────────────────────────


def test_log_info_prints_info_prefix(capsys):
    deploy.log_info("hello world")
    out = capsys.readouterr().out
    assert "INFO" in out
    assert "hello world" in out


def test_log_success_prints_success_prefix(capsys):
    deploy.log_success("all done")
    out = capsys.readouterr().out
    assert "SUCCESS" in out
    assert "all done" in out


def test_log_error_prints_error_prefix(capsys):
    deploy.log_error("something broke")
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "something broke" in out


def test_log_warning_prints_warning_prefix(capsys):
    deploy.log_warning("watch out")
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "watch out" in out


def test_error_exit_prints_and_exits_with_1(capsys):
    with pytest.raises(SystemExit) as exc:
        deploy.error_exit("fatal failure")
    assert exc.value.code == 1
    assert "fatal failure" in capsys.readouterr().out


# ── DeployConfig ────────────────────────────────────────────────────────────


def test_config_defaults_when_env_empty():
    c = deploy.DeployConfig(env={})
    assert c.terraform_dir == deploy.DEFAULT_TERRAFORM_DIR
    assert c.ansible_dir == deploy.DEFAULT_ANSIBLE_DIR
    assert c.ssh_user == deploy.DEFAULT_SSH_USER
    assert c.timeout == deploy.DEFAULT_TIMEOUT


def test_config_reads_env_overrides():
    c = deploy.DeployConfig(
        env={
            "TERRAFORM_DIR": "x",
            "ANSIBLE_DIR": "y",
            "SSH_USER": "root",
            "TIMEOUT": "123",
            "SOPS_AGE_KEY": "AGE-SECRET-KEY-1FAKE",
        }
    )
    assert c.terraform_dir == "x"
    assert c.ansible_dir == "y"
    assert c.ssh_user == "root"
    assert c.timeout == 123
    assert c.sops_age_key == "AGE-SECRET-KEY-1FAKE"


# ── check_prerequisites ─────────────────────────────────────────────────────


def test_check_prerequisites_success_when_all_tools_present(tmp_path, capsys):
    tf_dir = tmp_path / "tf"
    ans_dir = tmp_path / "ans"
    tf_dir.mkdir()
    ans_dir.mkdir()
    c = _config(
        env={
            "TERRAFORM_DIR": str(tf_dir),
            "ANSIBLE_DIR": str(ans_dir),
            "SOPS_AGE_KEY": "AGE-SECRET-KEY-1FAKE",
        }
    )

    def fake_which(cmd):
        return f"/usr/bin/{cmd}"

    with patch("deploy_aws_homelab.shutil.which", side_effect=fake_which), patch(
        "deploy_aws_homelab.subprocess.run", return_value=_proc(0)
    ):
        deploy.check_prerequisites(c)
    assert "All prerequisites met" in capsys.readouterr().out


def test_check_prerequisites_exits_1_when_terraform_missing():
    c = _config()
    with patch("deploy_aws_homelab.shutil.which", return_value=None):
        with pytest.raises(SystemExit) as exc:
            deploy.check_prerequisites(c)
    assert exc.value.code == 1


def test_check_prerequisites_exits_1_when_ansible_missing(capsys):
    c = _config()
    with patch(
        "deploy_aws_homelab.shutil.which",
        side_effect=lambda name: "/u/b/" + name if name == "terraform" else None,
    ):
        with pytest.raises(SystemExit):
            deploy.check_prerequisites(c)
    assert "Ansible" in capsys.readouterr().out


def test_check_prerequisites_exits_1_when_aws_missing(capsys):
    c = _config()

    def fake_which(cmd):
        return "/u/b/x" if cmd in ("terraform", "ansible-playbook") else None

    with patch("deploy_aws_homelab.shutil.which", side_effect=fake_which):
        with pytest.raises(SystemExit):
            deploy.check_prerequisites(c)
    assert "AWS CLI" in capsys.readouterr().out


def test_check_prerequisites_exits_1_when_terraform_dir_missing(tmp_path, capsys):
    ans_dir = tmp_path / "ans"
    ans_dir.mkdir()
    c = _config(env={"TERRAFORM_DIR": "/no-such-dir", "ANSIBLE_DIR": str(ans_dir)})
    with patch("deploy_aws_homelab.shutil.which", side_effect=lambda n: "/u/b/" + n):
        with pytest.raises(SystemExit):
            deploy.check_prerequisites(c)
    assert "Terraform directory" in capsys.readouterr().out


def test_check_prerequisites_exits_1_when_ansible_dir_missing(tmp_path, capsys):
    tf_dir = tmp_path / "tf"
    tf_dir.mkdir()
    c = _config(env={"TERRAFORM_DIR": str(tf_dir), "ANSIBLE_DIR": "/no-such-dir"})
    with patch("deploy_aws_homelab.shutil.which", side_effect=lambda n: "/u/b/" + n):
        with pytest.raises(SystemExit):
            deploy.check_prerequisites(c)
    assert "Ansible directory" in capsys.readouterr().out


# ── check_sops_key ──────────────────────────────────────────────────────────


def test_check_sops_key_exits_1_when_sops_not_found(capsys):
    c = _config()
    with patch("deploy_aws_homelab.shutil.which", return_value=None):
        with pytest.raises(SystemExit):
            deploy.check_sops_key(c)
    assert "sops not found" in capsys.readouterr().out


def test_check_sops_key_exits_1_when_no_age_key(capsys):
    c = _config(env={})
    with patch("deploy_aws_homelab.shutil.which", return_value="/usr/bin/sops"):
        with pytest.raises(SystemExit):
            deploy.check_sops_key(c)
    assert "Age key not configured" in capsys.readouterr().out


def test_check_sops_key_succeeds_with_env_key(capsys):
    c = _config(env={"SOPS_AGE_KEY": "AGE-SECRET-KEY-1FAKE"})
    with patch("deploy_aws_homelab.shutil.which", return_value="/usr/bin/sops"), patch(
        "deploy_aws_homelab.subprocess.run", return_value=_proc(0)
    ):
        deploy.check_sops_key(c)
    assert "SOPS decryption verified" in capsys.readouterr().out


def test_check_sops_key_exits_1_on_decryption_failure(capsys):
    c = _config(env={"SOPS_AGE_KEY": "AGE-SECRET-KEY-1FAKE"})
    failure = subprocess.CalledProcessError(returncode=1, cmd=["sops"])
    with patch("deploy_aws_homelab.shutil.which", return_value="/usr/bin/sops"), patch(
        "deploy_aws_homelab.subprocess.run", side_effect=failure
    ):
        with pytest.raises(SystemExit):
            deploy.check_sops_key(c)
    assert "SOPS decryption failed" in capsys.readouterr().out


def test_check_sops_key_accepts_key_file(tmp_path):
    key = tmp_path / "age.txt"
    key.write_text("AGE-SECRET-KEY-1FAKE\n")
    c = _config(env={"SOPS_AGE_KEY_FILE": str(key)})
    with patch("deploy_aws_homelab.shutil.which", return_value="/usr/bin/sops"), patch(
        "deploy_aws_homelab.subprocess.run", return_value=_proc(0)
    ):
        deploy.check_sops_key(c)  # should not raise


# ── check_aws_account ──────────────────────────────────────────────────────


def test_check_aws_account_skips_when_not_configured(capsys):
    c = _config(env={})
    with patch("deploy_aws_homelab.subprocess.run") as run:
        deploy.check_aws_account(c)
    assert run.call_count == 0
    assert "skipping AWS account identity check" in capsys.readouterr().out


def test_check_aws_account_succeeds_when_account_matches(capsys):
    c = _config(env={"HOMELAB_AWS_ACCOUNT_ID": "123456789012"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, stdout="123456789012\n"),
    ):
        deploy.check_aws_account(c)
    assert "AWS account verified: 123456789012" in capsys.readouterr().out


def test_check_aws_account_exits_1_on_account_mismatch(capsys):
    c = _config(env={"HOMELAB_AWS_ACCOUNT_ID": "123456789012"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, stdout="999999999999\n"),
    ):
        with pytest.raises(SystemExit) as exc:
            deploy.check_aws_account(c)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Wrong AWS account" in out
    assert "actual=999999999999" in out or "active=999999999999" in out


def test_check_aws_account_exits_1_when_sts_call_fails(capsys):
    c = _config(env={"HOMELAB_AWS_ACCOUNT_ID": "123456789012"})
    failure = subprocess.CalledProcessError(
        returncode=255, cmd=["aws"], stderr="unable to locate credentials"
    )
    with patch("deploy_aws_homelab.subprocess.run", side_effect=failure):
        with pytest.raises(SystemExit):
            deploy.check_aws_account(c)
    assert "get-caller-identity failed" in capsys.readouterr().out


# ── wait_for_ssm ────────────────────────────────────────────────────────────


def test_wait_for_ssm_returns_true_on_immediate_online(capsys):
    c = _config(env={"TIMEOUT": "30"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, "Online\n"),
    ), patch("deploy_aws_homelab.time.sleep"):
        ok = deploy.wait_for_ssm("i-fake", c)
    assert ok is True
    assert "SSM ready" in capsys.readouterr().out


def test_wait_for_ssm_returns_false_on_timeout(capsys):
    c = _config(env={"TIMEOUT": "30"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, "None\n"),
    ), patch("deploy_aws_homelab.time.sleep"):
        ok = deploy.wait_for_ssm("i-fake", c)
    assert ok is False
    assert "Timeout" in capsys.readouterr().out


def test_wait_for_ssm_returns_true_on_second_attempt():
    c = _config(env={"TIMEOUT": "60"})
    responses = iter([_proc(0, "None\n"), _proc(0, "Online\n")])
    with patch(
        "deploy_aws_homelab.subprocess.run",
        side_effect=lambda *a, **kw: next(responses),
    ), patch("deploy_aws_homelab.time.sleep"):
        assert deploy.wait_for_ssm("i-fake", c) is True


# ── ssm_run ─────────────────────────────────────────────────────────────────


def _ssm_run_side_effect(status_seq, output):
    """Build a subprocess.run side_effect simulating send/poll/get."""
    poll_iter = iter(status_seq)

    def _runner(args, *a, **kw):
        joined = " ".join(args)
        if "send-command" in joined:
            return _proc(0, "cmd-abc\n")
        if "Status" in joined:
            try:
                return _proc(0, next(poll_iter) + "\n")
            except StopIteration:
                return _proc(0, "Success\n")
        if "StandardOutputContent" in joined:
            return _proc(0, output + "\n")
        return _proc(0, "")

    return _runner


def test_ssm_run_returns_output_on_first_success():
    with patch(
        "deploy_aws_homelab.subprocess.run",
        side_effect=_ssm_run_side_effect(["Success"], "instance output here"),
    ), patch("deploy_aws_homelab.time.sleep"):
        out = deploy.ssm_run("i-fake", "echo hello")
    assert out == "instance output here"


def test_ssm_run_polls_through_in_progress():
    with patch(
        "deploy_aws_homelab.subprocess.run",
        side_effect=_ssm_run_side_effect(
            ["InProgress", "InProgress", "Success"], "polled result"
        ),
    ), patch("deploy_aws_homelab.time.sleep"):
        out = deploy.ssm_run("i-fake", "slow-cmd")
    assert out == "polled result"


def test_ssm_run_returns_output_when_final_status_is_failed():
    with patch(
        "deploy_aws_homelab.subprocess.run",
        side_effect=_ssm_run_side_effect(["Failed"], "partial output before fail"),
    ), patch("deploy_aws_homelab.time.sleep"):
        out = deploy.ssm_run("i-fake", "failing-cmd")
    assert out == "partial output before fail"


# ── wait_for_tailscale_ip ───────────────────────────────────────────────────


def test_wait_for_tailscale_ip_succeeds_on_100_prefix(capsys):
    c = _config(env={"TIMEOUT": "30"})
    with patch("deploy_aws_homelab.ssm_run", return_value="100.64.0.42"), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        assert deploy.wait_for_tailscale_ip("i-n", c) is True
    assert "100.64.0.42" in capsys.readouterr().out


def test_wait_for_tailscale_ip_fails_on_non_tailscale_ip(capsys):
    c = _config(env={"TIMEOUT": "15"})
    with patch("deploy_aws_homelab.ssm_run", return_value="192.168.1.10"), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        assert deploy.wait_for_tailscale_ip("i-w", c) is False
    assert "Timeout" in capsys.readouterr().out


def test_wait_for_tailscale_ip_fails_on_empty():
    c = _config(env={"TIMEOUT": "15"})
    with patch("deploy_aws_homelab.ssm_run", return_value=""), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        assert deploy.wait_for_tailscale_ip("i-e", c) is False


def test_wait_for_tailscale_ip_strips_whitespace():
    c = _config(env={"TIMEOUT": "30"})
    with patch("deploy_aws_homelab.ssm_run", return_value="  100.64.0.1  \n"), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        assert deploy.wait_for_tailscale_ip("i-s", c) is True


# ── check_instance_count ────────────────────────────────────────────────────


def test_check_instance_count_passes_for_exactly_2(capsys):
    deploy.check_instance_count(2)
    assert "verified: 2/2" in capsys.readouterr().out


def test_check_instance_count_passes_for_1(capsys):
    deploy.check_instance_count(1)
    assert "verified: 1/2" in capsys.readouterr().out


def test_check_instance_count_aborts_for_3(capsys):
    with pytest.raises(SystemExit):
        deploy.check_instance_count(3)
    assert "Aborting to prevent orphans" in capsys.readouterr().out


# ── rewrite_kubeconfig ──────────────────────────────────────────────────────


FIXTURE = Path(__file__).parent / "fixtures/test-kubeconfig.yaml"


def test_rewrite_kubeconfig_replaces_127_0_0_1(tmp_path):
    dest = tmp_path / "kc.yaml"
    content = FIXTURE.read_text()
    deploy.rewrite_kubeconfig(content, "100.64.0.1", dest)
    text = dest.read_text()
    assert "100.64.0.1" in text
    assert "127.0.0.1" not in text


def test_rewrite_kubeconfig_leaves_non_matching_content_unchanged(tmp_path):
    dest = tmp_path / "kc.yaml"
    deploy.rewrite_kubeconfig("server: https://100.64.0.1:6443", "100.64.0.99", dest)
    text = dest.read_text()
    assert "100.64.0.1" in text
    assert "100.64.0.99" not in text


def test_rewrite_kubeconfig_sets_0600_permissions(tmp_path):
    dest = tmp_path / "kc.yaml"
    deploy.rewrite_kubeconfig(FIXTURE.read_text(), "100.64.0.2", dest)
    mode = dest.stat().st_mode & 0o777
    assert mode == 0o600


# ── destroy_infrastructure ──────────────────────────────────────────────────


def test_destroy_cancels_when_user_inputs_no(capsys):
    c = _config()
    with patch("builtins.input", return_value="no"), patch(
        "deploy_aws_homelab.subprocess.run"
    ) as mock_run:
        with pytest.raises(SystemExit) as exc:
            deploy.destroy_infrastructure(c)
    assert exc.value.code == 0
    assert "Destruction cancelled" in capsys.readouterr().out
    mock_run.assert_not_called()


def test_destroy_runs_terraform_when_user_inputs_yes():
    c = _config()
    with patch("builtins.input", return_value="yes"), patch(
        "deploy_aws_homelab.subprocess.run", return_value=_proc(0)
    ) as mock_run:
        with pytest.raises(SystemExit) as exc:
            deploy.destroy_infrastructure(c)
    assert exc.value.code == 0
    # Expect both the cleanup playbook and terraform destroy
    called_cmds = [call.args[0] for call in mock_run.call_args_list]
    assert any(c[0] == "terraform" and "destroy" in c for c in called_cmds)


def test_destroy_continues_when_tailscale_cleanup_fails(capsys):
    c = _config()
    results = iter([_proc(1), _proc(0)])  # ansible-playbook fails, terraform ok
    with patch("builtins.input", return_value="yes"), patch(
        "deploy_aws_homelab.subprocess.run", side_effect=lambda *a, **kw: next(results)
    ):
        with pytest.raises(SystemExit) as exc:
            deploy.destroy_infrastructure(c)
    assert exc.value.code == 0
    assert "Could not clean up Tailscale" in capsys.readouterr().out


def test_destroy_exits_1_when_terraform_destroy_fails():
    c = _config()
    results = iter([_proc(0), _proc(1)])
    with patch("builtins.input", return_value="yes"), patch(
        "deploy_aws_homelab.subprocess.run", side_effect=lambda *a, **kw: next(results)
    ):
        with pytest.raises(SystemExit) as exc:
            deploy.destroy_infrastructure(c)
    assert exc.value.code == 1


# ── phase1_terraform ────────────────────────────────────────────────────────


def test_phase1_terraform_runs_full_sequence(tmp_path):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})
    calls = []

    def _run(args, *a, **kw):
        calls.append(list(args))
        return _proc(0, "tailscale_acl.homelab_acl\n")

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        deploy.phase1_terraform(c)

    cmds = [" ".join(c) for c in calls]
    assert any("init -upgrade" in c for c in cmds)
    assert any("validate" in c for c in cmds)
    assert any("apply -auto-approve" in c for c in cmds)
    assert any("apply -refresh-only -auto-approve" in c for c in cmds)


def test_phase1_terraform_imports_acl_when_missing(tmp_path):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})
    calls = []

    def _run(args, *a, **kw):
        calls.append(list(args))
        # state list returns empty (ACL missing)
        if "state" in args and "list" in args:
            return _proc(0, "")
        return _proc(0, "")

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        deploy.phase1_terraform(c)

    cmds = [" ".join(c) for c in calls]
    assert any("import tailscale_acl.homelab_acl acl" in c for c in cmds)


def test_phase1_terraform_exits_1_on_init_failure(tmp_path, capsys):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "init" in args:
            return _proc(1)
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit) as exc:
            deploy.phase1_terraform(c)
    assert exc.value.code == 1
    assert "Terraform init failed" in capsys.readouterr().out


# ── phase3_ansible ──────────────────────────────────────────────────────────


def test_phase3_ansible_runs_site_playbook(tmp_path):
    c = _config(env={"ANSIBLE_DIR": str(tmp_path)})
    (tmp_path / "terraform_inventory_aws.py").write_text("#!/usr/bin/env python3\n")
    calls = []

    def _run(args, *a, **kw):
        calls.append(list(args))
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        deploy.phase3_ansible(c)

    cmds = [" ".join(c) for c in calls]
    assert any(
        "ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml" in c
        for c in cmds
    )


def test_phase3_ansible_exits_1_when_inventory_missing(tmp_path, capsys):
    c = _config(env={"ANSIBLE_DIR": str(tmp_path)})
    with pytest.raises(SystemExit):
        deploy.phase3_ansible(c)
    assert "Dynamic inventory script not found" in capsys.readouterr().out


def test_phase3_ansible_exits_1_when_playbook_fails(tmp_path, capsys):
    c = _config(env={"ANSIBLE_DIR": str(tmp_path)})
    (tmp_path / "terraform_inventory_aws.py").write_text("")

    def _run(args, *a, **kw):
        if args and args[0] == "ansible-playbook":
            return _proc(1)
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit):
            deploy.phase3_ansible(c)
    assert "Ansible playbook failed" in capsys.readouterr().out


# ── phase4_verify ───────────────────────────────────────────────────────────


KUBECONFIG_YAML = (
    "apiVersion: v1\n"
    "clusters:\n"
    "- cluster:\n"
    "    server: https://127.0.0.1:6443\n"
    "  name: default\n"
)


def test_phase4_verify_writes_kubeconfig_with_tailscale_endpoint(tmp_path, monkeypatch):
    kc_dest = tmp_path / "kc.yaml"
    monkeypatch.setattr(deploy, "KUBECONFIG_DEST", str(kc_dest))
    c = _config()
    c.server_id = "i-server123"

    responses = iter(["kubectl nodes ok", KUBECONFIG_YAML, "100.64.0.50"])

    def fake_ssm_run(instance_id, command):
        return next(responses)

    with patch("deploy_aws_homelab.ssm_run", side_effect=fake_ssm_run):
        deploy.phase4_verify(c)

    assert kc_dest.is_file()
    text = kc_dest.read_text()
    assert "100.64.0.50" in text
    assert "127.0.0.1" not in text


def test_phase4_verify_warns_when_kubeconfig_empty(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(deploy, "KUBECONFIG_DEST", str(tmp_path / "kc.yaml"))
    c = _config()
    c.server_id = "i-server"

    def fake_ssm_run(instance_id, command):
        if "cat" in command:
            return ""
        if "tailscale" in command:
            return "100.64.0.1"
        return "ok"

    with patch("deploy_aws_homelab.ssm_run", side_effect=fake_ssm_run):
        deploy.phase4_verify(c)
    assert "Kubeconfig empty" in capsys.readouterr().out


def test_phase4_verify_skips_when_no_server_id_found(capsys):
    c = _config()
    c.server_id = None
    with patch("deploy_aws_homelab.subprocess.run", return_value=_proc(0, "")):
        deploy.phase4_verify(c)
    assert "Could not find server instance" in capsys.readouterr().out


# ── main CLI ────────────────────────────────────────────────────────────────


def test_main_destroy_branch():
    with patch(
        "deploy_aws_homelab.destroy_infrastructure", side_effect=SystemExit(0)
    ) as mock_destroy, patch("deploy_aws_homelab.print_banner"):
        with pytest.raises(SystemExit):
            deploy.main(["--destroy"])
    mock_destroy.assert_called_once()


def test_main_short_destroy_flag():
    with patch(
        "deploy_aws_homelab.destroy_infrastructure", side_effect=SystemExit(0)
    ) as mock_destroy, patch("deploy_aws_homelab.print_banner"):
        with pytest.raises(SystemExit):
            deploy.main(["-d"])
    mock_destroy.assert_called_once()


def test_main_full_deploy_runs_all_phases():
    stubs = {
        "check_prerequisites": MagicMock(),
        "phase1_terraform": MagicMock(),
        "phase2_wait_for_instances": MagicMock(),
        "phase2_5_wait_for_tailscale": MagicMock(),
        "phase3_ansible": MagicMock(),
        "phase4_verify": MagicMock(),
        "print_summary": MagicMock(),
        "print_banner": MagicMock(),
    }
    with patch.multiple("deploy_aws_homelab", **stubs):
        rc = deploy.main([])
    assert rc == 0
    for name, mock in stubs.items():
        if name != "print_banner":
            mock.assert_called_once()


def test_main_help_exits_0(capsys):
    with pytest.raises(SystemExit) as exc:
        deploy.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Zero Trust" in out


# ── aws helpers (describe / count) ─────────────────────────────────────────


def test_describe_instance_id_returns_trimmed():
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, "i-abc123\n"),
    ):
        assert deploy._describe_instance_id("hl-k3s-server") == "i-abc123"


def test_count_running_instances_returns_int():
    with patch("deploy_aws_homelab.subprocess.run", return_value=_proc(0, "2\n")):
        assert deploy._count_running_instances() == 2


def test_count_running_instances_returns_0_on_non_numeric():
    with patch("deploy_aws_homelab.subprocess.run", return_value=_proc(0, "bad\n")):
        assert deploy._count_running_instances() == 0


# ── phase2 orchestrator ─────────────────────────────────────────────────────


def test_phase2_exits_when_server_id_missing(capsys):
    c = _config()
    with patch("deploy_aws_homelab._describe_instance_id", return_value=""):
        with pytest.raises(SystemExit):
            deploy.phase2_wait_for_instances(c)
    assert "Could not find k3s-server" in capsys.readouterr().out


def test_phase2_exits_when_agent_id_missing(capsys):
    c = _config()
    with patch(
        "deploy_aws_homelab._describe_instance_id",
        side_effect=["i-server", ""],
    ):
        with pytest.raises(SystemExit):
            deploy.phase2_wait_for_instances(c)
    assert "Could not find k3s-agent" in capsys.readouterr().out


def test_phase2_exits_when_server_ssm_not_reachable(capsys):
    c = _config()
    with patch(
        "deploy_aws_homelab._describe_instance_id",
        side_effect=["i-server", "i-agent"],
    ), patch("deploy_aws_homelab._count_running_instances", return_value=2), patch(
        "deploy_aws_homelab.wait_for_ssm", return_value=False
    ):
        with pytest.raises(SystemExit):
            deploy.phase2_wait_for_instances(c)
    assert "Server SSM not reachable" in capsys.readouterr().out


def test_phase2_populates_config_ids_on_success():
    c = _config()
    with patch(
        "deploy_aws_homelab._describe_instance_id",
        side_effect=["i-server", "i-agent"],
    ), patch("deploy_aws_homelab._count_running_instances", return_value=2), patch(
        "deploy_aws_homelab.wait_for_ssm", return_value=True
    ):
        deploy.phase2_wait_for_instances(c)
    assert c.server_id == "i-server"
    assert c.agent_id == "i-agent"


def test_phase2_5_exits_when_server_tailscale_not_ready(capsys):
    c = _config()
    c.server_id = "i-server"
    c.agent_id = "i-agent"
    with patch("deploy_aws_homelab.wait_for_tailscale_ip", return_value=False):
        with pytest.raises(SystemExit):
            deploy.phase2_5_wait_for_tailscale(c)
    assert "Tailscale on server not ready" in capsys.readouterr().out


# ── SSM / Tailscale resilience to exceptions ────────────────────────────────


def test_wait_for_ssm_treats_subprocess_exception_as_none(capsys):
    c = _config(env={"TIMEOUT": "30"})
    with patch(
        "deploy_aws_homelab.subprocess.run", side_effect=RuntimeError("aws boom")
    ), patch("deploy_aws_homelab.time.sleep"):
        ok = deploy.wait_for_ssm("i-fail", c)
    assert ok is False
    assert "Timeout" in capsys.readouterr().out


def test_ssm_run_treats_status_exception_as_pending():
    calls = iter([_proc(0, "cmd-1\n")])

    def side_effect(args, *a, **kw):
        joined = " ".join(args)
        if "send-command" in joined:
            return next(calls)
        if "Status" in joined:
            raise RuntimeError("transient error")
        if "StandardOutputContent" in joined:
            return _proc(0, "eventual output\n")
        return _proc(0, "")

    with patch("deploy_aws_homelab.subprocess.run", side_effect=side_effect), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        out = deploy.ssm_run("i-fake", "cmd")
    assert out == "eventual output"


def test_wait_for_tailscale_ip_treats_ssm_exception_as_empty():
    c = _config(env={"TIMEOUT": "15"})
    with patch("deploy_aws_homelab.ssm_run", side_effect=RuntimeError("boom")), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        assert deploy.wait_for_tailscale_ip("i-err", c) is False


# ── phase1_terraform warning branches ───────────────────────────────────────


def test_phase1_terraform_warns_when_import_fails(tmp_path, capsys):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "state" in args and "list" in args:
            return _proc(0, "")  # ACL missing
        if "import" in args:
            return _proc(1)  # import fails
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        deploy.phase1_terraform(c)  # must not raise
    assert "Import failed" in capsys.readouterr().out


def test_phase1_terraform_warns_when_refresh_only_fails(tmp_path, capsys):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "-refresh-only" in args:
            return _proc(1)
        if "state" in args and "list" in args:
            return _proc(0, "tailscale_acl.homelab_acl\n")
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        deploy.phase1_terraform(c)  # must not raise
    assert "Refresh-only" in capsys.readouterr().out


def test_phase1_terraform_exits_1_when_validate_fails(tmp_path, capsys):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "validate" in args:
            return _proc(1)
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit):
            deploy.phase1_terraform(c)
    assert "Terraform validation failed" in capsys.readouterr().out


def test_phase1_terraform_exits_1_when_apply_fails(tmp_path, capsys):
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "apply" in args and "-refresh-only" not in args:
            return _proc(1)
        if "state" in args and "list" in args:
            return _proc(0, "tailscale_acl.homelab_acl\n")
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit):
            deploy.phase1_terraform(c)
    assert "Terraform apply failed" in capsys.readouterr().out


# ── phase2: agent paths ─────────────────────────────────────────────────────


def test_phase2_exits_when_agent_ssm_not_reachable(capsys):
    c = _config()
    with patch(
        "deploy_aws_homelab._describe_instance_id",
        side_effect=["i-server", "i-agent"],
    ), patch("deploy_aws_homelab._count_running_instances", return_value=2), patch(
        "deploy_aws_homelab.wait_for_ssm", side_effect=[True, False]
    ):
        with pytest.raises(SystemExit):
            deploy.phase2_wait_for_instances(c)
    assert "Agent SSM not reachable" in capsys.readouterr().out


def test_phase2_5_exits_when_agent_tailscale_not_ready(capsys):
    c = _config()
    c.server_id = "i-server"
    c.agent_id = "i-agent"
    with patch("deploy_aws_homelab.wait_for_tailscale_ip", side_effect=[True, False]):
        with pytest.raises(SystemExit):
            deploy.phase2_5_wait_for_tailscale(c)
    assert "Tailscale on agent not ready" in capsys.readouterr().out


# ── phase3: inventory + orchestration ───────────────────────────────────────


def test_phase3_ansible_exits_1_when_inventory_script_fails(tmp_path, capsys):
    c = _config(env={"ANSIBLE_DIR": str(tmp_path)})
    (tmp_path / "terraform_inventory_aws.py").write_text("")

    def _run(args, *a, **kw):
        if "terraform_inventory_aws.py" in args:
            return _proc(1)
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit):
            deploy.phase3_ansible(c)
    assert "Inventory script failed" in capsys.readouterr().out


# ── phase4: more branches ───────────────────────────────────────────────────


def test_phase4_verify_falls_back_to_describe_for_server_id(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "KUBECONFIG_DEST", str(tmp_path / "kc.yaml"))
    c = _config()
    c.server_id = None

    responses = iter(["kubectl ok", KUBECONFIG_YAML, "100.64.0.9"])

    def fake_ssm_run(instance_id, command):
        return next(responses)

    with patch(
        "deploy_aws_homelab._describe_instance_id", return_value="i-discovered"
    ), patch("deploy_aws_homelab.ssm_run", side_effect=fake_ssm_run):
        deploy.phase4_verify(c)

    kc = tmp_path / "kc.yaml"
    assert kc.is_file()
    assert "100.64.0.9" in kc.read_text()


def test_phase4_verify_warns_when_kubectl_check_raises(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(deploy, "KUBECONFIG_DEST", str(tmp_path / "kc.yaml"))
    c = _config()
    c.server_id = "i-server"

    call_counter = {"n": 0}

    def flaky_ssm_run(instance_id, command):
        call_counter["n"] += 1
        if "kubectl" in command:
            raise RuntimeError("kubectl not ready")
        if "cat" in command:
            return KUBECONFIG_YAML
        return "100.64.0.5"

    with patch("deploy_aws_homelab.ssm_run", side_effect=flaky_ssm_run):
        deploy.phase4_verify(c)
    assert "kubectl check failed" in capsys.readouterr().out


def test_phase4_verify_warns_when_no_tailscale_ip(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(deploy, "KUBECONFIG_DEST", str(tmp_path / "kc.yaml"))
    c = _config()
    c.server_id = "i-server"

    def fake_ssm_run(instance_id, command):
        if "cat" in command:
            return KUBECONFIG_YAML
        if "tailscale" in command:
            return ""
        return "ok"

    with patch("deploy_aws_homelab.ssm_run", side_effect=fake_ssm_run):
        deploy.phase4_verify(c)
    out = capsys.readouterr().out
    assert "Tailscale IP empty" in out
    assert "Kubeconfig not saved" in out


def test_phase4_verify_handles_both_kubeconfig_and_tailscale_exceptions(
    capsys, monkeypatch, tmp_path
):
    monkeypatch.setattr(deploy, "KUBECONFIG_DEST", str(tmp_path / "kc.yaml"))
    c = _config()
    c.server_id = "i-server"

    def raising_ssm_run(instance_id, command):
        raise RuntimeError("ssm flaky")

    with patch("deploy_aws_homelab.ssm_run", side_effect=raising_ssm_run):
        deploy.phase4_verify(c)
    out = capsys.readouterr().out
    assert "Kubeconfig empty" in out
    assert "Tailscale IP empty" in out


# ── print_banner / print_summary ────────────────────────────────────────────


def test_print_banner_prints_title(capsys):
    deploy.print_banner()
    out = capsys.readouterr().out
    assert "AWS HOMELAB DEPLOYMENT" in out
    assert "Terraform" in out


def test_print_summary_prints_all_sections(capsys):
    c = _config(env={"TERRAFORM_DIR": "tf"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, "203.0.113.5\n"),
    ):
        deploy.print_summary(c)
    out = capsys.readouterr().out
    assert "DEPLOYMENT COMPLETED SUCCESSFULLY" in out
    assert "Instance Information" in out
    assert "203.0.113.5" in out
    assert "ArgoCD" in out
    assert "Monitor" in out
    assert "Destroy" in out


def test_print_summary_falls_back_to_na_when_tf_output_fails(capsys):
    c = _config(env={"TERRAFORM_DIR": "tf"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(1, ""),
    ):
        deploy.print_summary(c)
    out = capsys.readouterr().out
    assert "k3s-server: N/A" in out
    assert "k3s-agent:  N/A" in out


def test_print_summary_falls_back_to_na_when_tf_output_empty(capsys):
    c = _config(env={"TERRAFORM_DIR": "tf"})
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, "   \n"),
    ):
        deploy.print_summary(c)
    out = capsys.readouterr().out
    assert "k3s-server: N/A" in out


# ── main orchestration calls banner ─────────────────────────────────────────


def test_main_calls_print_banner_on_deploy():
    stubs = {
        "check_prerequisites": MagicMock(),
        "phase1_terraform": MagicMock(),
        "phase2_wait_for_instances": MagicMock(),
        "phase2_5_wait_for_tailscale": MagicMock(),
        "phase3_ansible": MagicMock(),
        "phase4_verify": MagicMock(),
        "print_summary": MagicMock(),
        "print_banner": MagicMock(),
    }
    with patch.multiple("deploy_aws_homelab", **stubs):
        deploy.main([])
    stubs["print_banner"].assert_called_once()


def test_phase2_5_succeeds_when_both_instances_online(capsys):
    """Line 456 branch: log_success on happy path."""
    c = _config()
    c.server_id = "i-server"
    c.agent_id = "i-agent"
    with patch("deploy_aws_homelab.wait_for_tailscale_ip", return_value=True):
        deploy.phase2_5_wait_for_tailscale(c)
    assert "Tailscale is active on all instances" in capsys.readouterr().out


def test_main_destroy_returns_zero_after_cleanup():
    """Line 691 branch: main() returns 0 after destroy_infrastructure() completes."""
    with patch("deploy_aws_homelab.destroy_infrastructure") as mock_destroy, patch(
        "deploy_aws_homelab.print_banner"
    ):
        rc = deploy.main(["--destroy"])
    assert rc == 0
    mock_destroy.assert_called_once()


# ── Failure-path tests (Tier 3 — realistic failure scenarios) ────────────────


def test_wait_for_ssm_pending_status_never_becomes_online(capsys):
    """Instance reporting 'Pending' (or any non-Online status) indefinitely times out."""
    c = _config(env={"TIMEOUT": "30"})
    # AWS CLI with --query can return an empty string that we normalize to "None",
    # OR something like "Inactive". Any non-"Online" value must not break the loop.
    with patch(
        "deploy_aws_homelab.subprocess.run",
        return_value=_proc(0, "Inactive\n"),
    ), patch("deploy_aws_homelab.time.sleep"):
        ok = deploy.wait_for_ssm("i-stuck", c)
    assert ok is False
    assert "Timeout" in capsys.readouterr().out


def test_wait_for_ssm_recovers_from_connection_lost_to_online():
    """Transient ConnectionLost must not be treated as permanent."""
    c = _config(env={"TIMEOUT": "60"})
    responses = iter([_proc(0, "ConnectionLost\n"), _proc(0, "Online\n")])
    with patch(
        "deploy_aws_homelab.subprocess.run",
        side_effect=lambda *a, **kw: next(responses),
    ), patch("deploy_aws_homelab.time.sleep"):
        assert deploy.wait_for_ssm("i-flap", c) is True


def test_phase1_terraform_apply_exit_2_surfaces_lock_error(tmp_path, capsys):
    """terraform apply exit 2 (state lock held) must abort with clear error."""
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "apply" in args and "-auto-approve" in args:
            # Exit 2 with stderr mentioning lock
            return _proc(2, "", "Error acquiring the state lock")
        if "state" in args and "list" in args:
            return _proc(0, "tailscale_acl.homelab_acl\n")
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit) as exc:
            deploy.phase1_terraform(c)
    assert exc.value.code == 1
    assert "Terraform apply failed" in capsys.readouterr().out


def test_phase1_terraform_refresh_only_failure_is_warning_not_fatal(tmp_path, capsys):
    """Refresh-only pass is advisory; failure must log warning but not abort."""
    c = _config(env={"TERRAFORM_DIR": str(tmp_path)})

    def _run(args, *a, **kw):
        if "-refresh-only" in args:
            return _proc(1, "", "refresh failed")
        if "state" in args and "list" in args:
            return _proc(0, "tailscale_acl.homelab_acl\n")
        return _proc(0)

    with patch("deploy_aws_homelab.subprocess.run", side_effect=_run):
        deploy.phase1_terraform(c)  # must NOT raise
    out = capsys.readouterr().out
    assert "Refresh-only pass failed" in out


def test_ssm_run_returns_stdout_even_when_status_is_failed():
    """If the remote command returns Failed status, we still read stdout for diagnostics."""
    with patch(
        "deploy_aws_homelab.subprocess.run",
        side_effect=_ssm_run_side_effect(["Failed"], "error: command not found\n"),
    ), patch("deploy_aws_homelab.time.sleep"):
        out = deploy.ssm_run("i-fake", "nonexistent-cmd")
    assert "error:" in out or "command not found" in out


def test_check_instance_count_aborts_when_more_than_two(capsys):
    """Safety gate: refuse to proceed if stale instances from prior deploy exist."""
    with pytest.raises(SystemExit) as exc:
        deploy.check_instance_count(4)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "4" in out
    assert "orphan" in out.lower() or "cleanup" in out.lower()


def test_rewrite_kubeconfig_only_replaces_localhost_not_private_ips(tmp_path):
    """Must not mangle other IPs that happen to contain '127' or use 10.x.x.x."""
    dest = tmp_path / "kubeconfig.yaml"
    content = (
        "server: https://127.0.0.1:6443\n"
        "  cluster-cidr: 10.42.0.0/16\n"
        "  advertise: 10.0.1.42\n"
        "  not-localhost: 172.27.127.1\n"
    )
    deploy.rewrite_kubeconfig(content, "100.101.102.103", dest)
    result = dest.read_text()
    assert "100.101.102.103:6443" in result
    assert "10.42.0.0/16" in result  # CIDR intact
    assert "10.0.1.42" in result  # private IP intact
    assert "172.27.127.1" in result  # no 127.0.0.1 substring match
    assert "127.0.0.1" not in result


def test_rewrite_kubeconfig_sets_0600_permissions(tmp_path):
    """Security: kubeconfig written must be 0600 (owner read/write only)."""
    dest = tmp_path / "kc.yaml"
    deploy.rewrite_kubeconfig("server: https://127.0.0.1:6443", "100.1.1.1", dest)
    mode = dest.stat().st_mode & 0o777
    assert mode == 0o600


def test_check_prerequisites_exits_cleanly_when_sops_key_file_points_to_missing_file(
    tmp_path, capsys
):
    """SOPS_AGE_KEY_FILE pointing to non-existent path → prerequisite failure."""
    c = _config(env={"SOPS_AGE_KEY_FILE": str(tmp_path / "does_not_exist")})
    with patch("deploy_aws_homelab.shutil.which", return_value="/usr/bin/sops"):
        with pytest.raises(SystemExit) as exc:
            deploy.check_sops_key(c)
    assert exc.value.code == 1
    assert "Age key not configured" in capsys.readouterr().out


def test_wait_for_tailscale_ip_pending_state_times_out():
    """Tailscale never assigns IP within timeout → phase2.5 fails loudly."""
    c = _config(env={"TIMEOUT": "30"})

    def _always_empty(*a, **kw):
        # ssm_run wrapped, returns empty IP every time
        return _proc(0, "\n")

    with patch("deploy_aws_homelab.ssm_run", return_value=""), patch(
        "deploy_aws_homelab.time.sleep"
    ):
        assert deploy.wait_for_tailscale_ip("i-late", c) is False
