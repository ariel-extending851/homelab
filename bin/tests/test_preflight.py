"""Tests for bin/preflight.py — pure parsers, exit-code mapping, skip flags."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import preflight  # noqa: E402


# ── pure parsers ─────────────────────────────────────────────────────────────


def test_parse_inventory_hosts_flat():
    yaml_text = """
all:
  hosts:
    srv1:
      ansible_host: 10.0.0.1
      ansible_user: pi
    srv2:
      ansible_host: 10.0.0.2
"""
    hosts = preflight.parse_inventory_hosts(yaml_text)
    assert hosts == [("srv1", "10.0.0.1"), ("srv2", "10.0.0.2")]


def test_parse_inventory_hosts_nested_groups():
    yaml_text = """
all:
  children:
    rpi:
      hosts:
        pi1:
          ansible_host: 192.168.1.10
    aws:
      children:
        k3s:
          hosts:
            server:
              ansible_host: 100.64.0.1
"""
    hosts = preflight.parse_inventory_hosts(yaml_text)
    names = [n for n, _ in hosts]
    assert "pi1" in names and "server" in names


def test_parse_inventory_hosts_skips_missing_ansible_host():
    yaml_text = """
all:
  hosts:
    srv1:
      ansible_host: 10.0.0.1
    srv2:
      ansible_user: pi
"""
    hosts = preflight.parse_inventory_hosts(yaml_text)
    assert hosts == [("srv1", "10.0.0.1")]


def test_parse_inventory_hosts_bad_yaml_returns_empty():
    assert preflight.parse_inventory_hosts("not: [unclosed") == []


def test_parse_tailscale_status_running():
    payload = {
        "BackendState": "Running",
        "Peer": {
            "a": {"Online": True},
            "b": {"Online": False},
            "c": {"Online": True},
        },
    }
    state, online = preflight.parse_tailscale_status(json.dumps(payload))
    assert state == "Running"
    assert online == 2


def test_parse_tailscale_status_blank():
    assert preflight.parse_tailscale_status("") == ("", 0)
    assert preflight.parse_tailscale_status("nonsense") == ("", 0)


def test_parse_ssm_online_counts_only_online():
    payload = {
        "InstanceInformationList": [
            {"PingStatus": "Online"},
            {"PingStatus": "ConnectionLost"},
            {"PingStatus": "Online"},
        ]
    }
    assert preflight.parse_ssm_online(json.dumps(payload)) == 2


def test_parse_ssm_online_empty():
    assert preflight.parse_ssm_online("") == 0
    assert preflight.parse_ssm_online("{}") == 0


def test_parse_sts_identity_ok():
    payload = {"Account": "123", "Arn": "arn:aws:iam::123:user/x"}
    account, arn = preflight.parse_sts_identity(json.dumps(payload))
    assert account == "123"
    assert arn.startswith("arn:aws:iam::")


def test_parse_sts_identity_bad_json():
    assert preflight.parse_sts_identity("not json") == ("", "")


# ── exit-code mapping ────────────────────────────────────────────────────────


def _args(**overrides):
    defaults = dict(
        skip_aws=True,
        skip_ssh=True,
        output="text",
        kubeconfig=None,
        timeout=5,
    )
    defaults.update(overrides)
    return type("A", (), defaults)()


def test_exit_code_clean():
    pf = preflight.Preflight(_args())
    pf.pass_("a")
    pf.pass_("b")
    assert pf.exit_code() == 0


def test_exit_code_warn_only():
    pf = preflight.Preflight(_args())
    pf.pass_("a")
    pf.warn("b", "careful")
    assert pf.exit_code() == 2


def test_exit_code_fail_trumps_warn():
    pf = preflight.Preflight(_args())
    pf.warn("a")
    pf.fail("b", "bad")
    assert pf.exit_code() == 1


def test_exit_code_skip_only():
    pf = preflight.Preflight(_args())
    pf.skip("a", "reason")
    assert pf.exit_code() == 0


# ── rendering ────────────────────────────────────────────────────────────────


def test_render_text_contains_markers_and_counts():
    pf = preflight.Preflight(_args())
    pf.pass_("tool.sops", "present")
    pf.fail("kube.config", "empty")
    buf = io.StringIO()
    pf.render(buf)
    out = buf.getvalue()
    assert "tool.sops" in out
    assert "kube.config" in out
    assert "✓" in out and "✗" in out
    assert "1 pass" in out and "1 fail" in out


def test_render_json_is_valid():
    pf = preflight.Preflight(_args(output="json"))
    pf.pass_("x", "ok")
    buf = io.StringIO()
    pf.render(buf)
    doc = json.loads(buf.getvalue())
    assert doc["command"] == "preflight"
    assert len(doc["checks"]) == 1
    assert doc["checks"][0] == {"name": "x", "status": "pass", "message": "ok"}


# ── skip flag behavior ───────────────────────────────────────────────────────


def test_skip_aws_flag_skips_creds_and_ssm():
    pf = preflight.Preflight(_args(skip_aws=True))
    pf.check_aws_creds()
    pf.check_aws_ssm()
    names = {c["name"]: c["status"] for c in pf.checks}
    assert names["aws.creds"] == "skip"
    assert names["aws.ssm"] == "skip"


def test_skip_ssh_flag_skips_ssh():
    pf = preflight.Preflight(_args(skip_ssh=True))
    pf.check_ssh()
    assert pf.checks[-1] == {
        "name": "ssh.reach",
        "status": "skip",
        "message": "--skip-ssh",
    }


# ── individual checks with mocks ─────────────────────────────────────────────


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


@patch("preflight.shutil.which")
def test_check_tools_reports_missing(mock_which):
    # Only terraform + python3 are present; everything else missing.
    mock_which.side_effect = lambda t: (
        "/usr/bin/" + t if t in ("terraform", "python3") else None
    )
    pf = preflight.Preflight(_args())
    pf.check_tools()
    by_name = {c["name"]: c["status"] for c in pf.checks}
    assert by_name["tool.terraform"] == "pass"
    assert by_name["tool.python3"] == "pass"
    assert by_name["tool.ansible"] == "fail"
    assert by_name["tool.sops"] == "fail"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_sops_decrypt_pass(mock_which, mock_run, tmp_path, monkeypatch):
    canary = tmp_path / "canary.yaml"
    canary.write_text("x")
    monkeypatch.setattr(preflight, "SOPS_CANARY", canary)
    mock_which.return_value = "/usr/bin/sops"
    mock_run.return_value = _proc(0, "decrypted", "")
    pf = preflight.Preflight(_args())
    pf.check_sops_decrypt()
    assert pf.checks[-1]["status"] == "pass"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_sops_decrypt_fail_is_loud(mock_which, mock_run, tmp_path, monkeypatch):
    canary = tmp_path / "canary.yaml"
    canary.write_text("x")
    monkeypatch.setattr(preflight, "SOPS_CANARY", canary)
    mock_which.return_value = "/usr/bin/sops"
    mock_run.return_value = _proc(1, "", "cannot decrypt")
    pf = preflight.Preflight(_args())
    pf.check_sops_decrypt()
    last = pf.checks[-1]
    assert last["status"] == "fail"
    assert "mock secrets" in last["message"]


def test_check_sops_skip_when_canary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "SOPS_CANARY", tmp_path / "does-not-exist.yaml")
    pf = preflight.Preflight(_args())
    pf.check_sops_decrypt()
    assert pf.checks[-1]["status"] == "skip"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_tailscale_pass(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/tailscale"
    mock_run.return_value = _proc(
        0, json.dumps({"BackendState": "Running", "Peer": {"x": {"Online": True}}})
    )
    pf = preflight.Preflight(_args())
    pf.check_tailscale()
    assert pf.checks[-1]["status"] == "pass"
    assert "1 peer" in pf.checks[-1]["message"]


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_tailscale_fail_on_stopped(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/tailscale"
    mock_run.return_value = _proc(
        0, json.dumps({"BackendState": "Stopped", "Peer": {}})
    )
    pf = preflight.Preflight(_args())
    pf.check_tailscale()
    assert pf.checks[-1]["status"] == "fail"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_aws_ssm_warns_when_no_instances(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/aws"
    mock_run.return_value = _proc(0, json.dumps({"InstanceInformationList": []}))
    pf = preflight.Preflight(_args(skip_aws=False))
    pf.check_aws_ssm()
    assert pf.checks[-1]["status"] == "warn"


def test_build_arg_parser_defaults():
    p = preflight.build_arg_parser()
    args = p.parse_args([])
    assert args.skip_aws is False
    assert args.skip_ssh is False
    assert args.output == "text"


def test_build_arg_parser_rejects_bad_output():
    import pytest

    p = preflight.build_arg_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["-o", "xml"])


# ── main() integration (skip most checks) ───────────────────────────────────


@patch("preflight.shutil.which", return_value="/usr/bin/fake")
@patch("preflight.subprocess.run")
def test_main_all_skipped_exits_on_tool_checks(
    mock_run, _mock_which, monkeypatch, tmp_path
):
    # With fake tools present and external probes skipped, everything passes.
    monkeypatch.setattr(preflight, "SOPS_CANARY", tmp_path / "nope.yaml")
    monkeypatch.setattr(preflight, "ANSIBLE_INVENTORY", tmp_path / "nope.yml")
    mock_run.return_value = _proc(
        0, json.dumps({"BackendState": "Running", "Peer": {}})
    )
    code = preflight.main(["--skip-aws", "--skip-ssh", "-o", "json"])
    assert code in (0, 2)  # kube/git may warn; no fail expected
