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
        planned_instances=4,
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


# ── #7 AWS quota headroom (RunInstances) ───────────────────────────────────


def test_parse_quota_response_returns_value():
    """Standard get-service-quota JSON shape: Quota.Value is an integer/float."""
    payload = json.dumps({"Quota": {"Value": 256.0, "QuotaCode": "L-1216C47A"}})
    assert preflight.parse_quota_response(payload) == 256


def test_parse_quota_response_blank_returns_zero():
    assert preflight.parse_quota_response("") == 0
    assert preflight.parse_quota_response("not-json") == 0


def test_parse_quota_response_missing_value_returns_zero():
    assert preflight.parse_quota_response(json.dumps({"Quota": {}})) == 0


def test_check_aws_quota_skipped_when_skip_aws():
    pf = preflight.Preflight(_args(skip_aws=True))
    pf.check_aws_quota()
    assert pf.checks[-1]["status"] == "skip"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_aws_quota_pass_with_headroom(mock_which, mock_run):
    """quota >= 4× planned should pass (default planned=4 → need 16)."""
    mock_which.return_value = "/usr/bin/aws"
    mock_run.return_value = _proc(0, json.dumps({"Quota": {"Value": 256}}))
    pf = preflight.Preflight(_args(skip_aws=False))
    pf.check_aws_quota()
    last = pf.checks[-1]
    assert last["status"] == "pass"
    assert "256" in last["message"]


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_aws_quota_warn_below_4x_planned(mock_which, mock_run):
    """quota present but < 4× planned → warn (not fail; user may proceed)."""
    mock_which.return_value = "/usr/bin/aws"
    mock_run.return_value = _proc(0, json.dumps({"Quota": {"Value": 8}}))
    pf = preflight.Preflight(_args(skip_aws=False, planned_instances=4))
    pf.check_aws_quota()
    assert pf.checks[-1]["status"] == "warn"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_aws_quota_fail_below_planned(mock_which, mock_run):
    """quota < planned instance count → fail (deploy will throttle/fail)."""
    mock_which.return_value = "/usr/bin/aws"
    mock_run.return_value = _proc(0, json.dumps({"Quota": {"Value": 2}}))
    pf = preflight.Preflight(_args(skip_aws=False, planned_instances=4))
    pf.check_aws_quota()
    assert pf.checks[-1]["status"] == "fail"


# ── #8 Tailscale key expiry ────────────────────────────────────────────────


def test_parse_tailscale_key_expiry_seconds_remaining():
    """Self.KeyExpiry is RFC3339; helper returns seconds-until-expiry."""
    from datetime import datetime, timedelta, timezone

    soon = (
        (datetime.now(timezone.utc) + timedelta(hours=2))
        .isoformat()
        .replace("+00:00", "Z")
    )
    payload = json.dumps({"Self": {"KeyExpiry": soon}})
    secs = preflight.parse_tailscale_key_expiry(payload)
    # Allow a small window for clock skew during test execution.
    assert 7100 <= secs <= 7300  # ~2h


def test_parse_tailscale_key_expiry_no_key_returns_negative():
    """Missing or never-expires key → return -1 sentinel (no warn fired)."""
    assert preflight.parse_tailscale_key_expiry("") == -1
    assert preflight.parse_tailscale_key_expiry("{}") == -1
    assert preflight.parse_tailscale_key_expiry(json.dumps({"Self": {}})) == -1


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_tailscale_key_expiry_warn_under_24h(mock_which, mock_run):
    from datetime import datetime, timedelta, timezone

    expiry = (
        (datetime.now(timezone.utc) + timedelta(hours=12))
        .isoformat()
        .replace("+00:00", "Z")
    )
    mock_which.return_value = "/usr/bin/tailscale"
    mock_run.return_value = _proc(
        0, json.dumps({"BackendState": "Running", "Self": {"KeyExpiry": expiry}})
    )
    pf = preflight.Preflight(_args())
    pf.check_tailscale_key_expiry()
    last = pf.checks[-1]
    assert last["status"] == "warn"
    assert "expires" in last["message"].lower() or "h" in last["message"]


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_tailscale_key_expiry_pass_more_than_24h(mock_which, mock_run):
    from datetime import datetime, timedelta, timezone

    expiry = (
        (datetime.now(timezone.utc) + timedelta(days=30))
        .isoformat()
        .replace("+00:00", "Z")
    )
    mock_which.return_value = "/usr/bin/tailscale"
    mock_run.return_value = _proc(
        0, json.dumps({"BackendState": "Running", "Self": {"KeyExpiry": expiry}})
    )
    pf = preflight.Preflight(_args())
    pf.check_tailscale_key_expiry()
    assert pf.checks[-1]["status"] == "pass"


# ── #10 CNI race guard ─────────────────────────────────────────────────────


def test_parse_cni_daemonset_status_all_ready():
    """flannel/cilium/calico DaemonSets in kube-system all converged."""
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "kube-flannel-ds", "namespace": "kube-system"},
                    "status": {"desiredNumberScheduled": 4, "numberReady": 4},
                }
            ]
        }
    )
    diverged = preflight.parse_cni_daemonset_status(payload)
    assert diverged == []  # no divergence


def test_parse_cni_daemonset_status_diverged():
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "cilium", "namespace": "kube-system"},
                    "status": {"desiredNumberScheduled": 4, "numberReady": 2},
                },
                {
                    "metadata": {"name": "calico-node", "namespace": "kube-system"},
                    "status": {"desiredNumberScheduled": 4, "numberReady": 4},
                },
            ]
        }
    )
    diverged = preflight.parse_cni_daemonset_status(payload)
    assert len(diverged) == 1
    assert diverged[0]["name"] == "cilium"
    assert diverged[0]["ready"] == 2
    assert diverged[0]["desired"] == 4


def test_parse_cni_daemonset_status_no_cni_found_returns_none_marker():
    """No flannel/cilium/calico DS at all → caller should skip, not fail.

    Helper signals "no CNI matched" via a None return distinct from [].
    """
    payload = json.dumps({"items": []})
    assert preflight.parse_cni_daemonset_status(payload) is None


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_cni_ready_pass_when_converged(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/kubectl"
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "cilium", "namespace": "kube-system"},
                    "status": {"desiredNumberScheduled": 4, "numberReady": 4},
                }
            ]
        }
    )
    mock_run.return_value = _proc(0, payload)
    pf = preflight.Preflight(_args())
    pf.check_cni_ready()
    assert pf.checks[-1]["status"] == "pass"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_cni_ready_fail_when_diverged(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/kubectl"
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "kube-flannel-ds", "namespace": "kube-system"},
                    "status": {"desiredNumberScheduled": 4, "numberReady": 1},
                }
            ]
        }
    )
    mock_run.return_value = _proc(0, payload)
    pf = preflight.Preflight(_args())
    pf.check_cni_ready()
    last = pf.checks[-1]
    assert last["status"] == "fail"
    assert "1/4" in last["message"]


# ── #12 Velero last-backup freshness ───────────────────────────────────────


def test_parse_velero_backup_freshness_no_backups_returns_none():
    """No Velero backups at all → None (caller surfaces 'no backups' warn)."""
    assert preflight.parse_velero_backup_freshness(json.dumps({"items": []})) is None


def test_parse_velero_backup_freshness_returns_age_in_seconds():
    from datetime import datetime, timedelta, timezone

    twelve_hours_ago = (
        (datetime.now(timezone.utc) - timedelta(hours=12))
        .isoformat()
        .replace("+00:00", "Z")
    )
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "old-backup"},
                    "status": {
                        "phase": "Completed",
                        "completionTimestamp": (
                            datetime.now(timezone.utc) - timedelta(days=5)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                    },
                },
                {
                    "metadata": {"name": "fresh-backup"},
                    "status": {
                        "phase": "Completed",
                        "completionTimestamp": twelve_hours_ago,
                    },
                },
            ]
        }
    )
    age = preflight.parse_velero_backup_freshness(payload)
    # Returns the *newest* completed backup age in seconds.
    assert 11.5 * 3600 <= age <= 12.5 * 3600


def test_parse_velero_backup_freshness_skips_failed_backups():
    """Only Completed backups count — InProgress/Failed don't reset the SLA."""
    payload = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "failed-recent"},
                    "status": {
                        "phase": "Failed",
                        "completionTimestamp": "2099-01-01T00:00:00Z",
                    },
                }
            ]
        }
    )
    assert preflight.parse_velero_backup_freshness(payload) is None


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_velero_backup_fresh_pass_within_24h(mock_which, mock_run):
    from datetime import datetime, timedelta, timezone

    fresh = (
        (datetime.now(timezone.utc) - timedelta(hours=2))
        .isoformat()
        .replace("+00:00", "Z")
    )
    mock_which.return_value = "/usr/bin/kubectl"
    mock_run.return_value = _proc(
        0,
        json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": "b1"},
                        "status": {
                            "phase": "Completed",
                            "completionTimestamp": fresh,
                        },
                    }
                ]
            }
        ),
    )
    pf = preflight.Preflight(_args())
    pf.check_velero_backup_fresh()
    assert pf.checks[-1]["status"] == "pass"


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_velero_backup_fresh_warn_over_24h(mock_which, mock_run):
    from datetime import datetime, timedelta, timezone

    stale = (
        (datetime.now(timezone.utc) - timedelta(days=2))
        .isoformat()
        .replace("+00:00", "Z")
    )
    mock_which.return_value = "/usr/bin/kubectl"
    mock_run.return_value = _proc(
        0,
        json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": "b1"},
                        "status": {
                            "phase": "Completed",
                            "completionTimestamp": stale,
                        },
                    }
                ]
            }
        ),
    )
    pf = preflight.Preflight(_args())
    pf.check_velero_backup_fresh()
    last = pf.checks[-1]
    assert last["status"] == "warn"
    assert "stale" in last["message"].lower() or "h ago" in last["message"]


@patch("preflight.subprocess.run")
@patch("preflight.shutil.which")
def test_check_velero_backup_fresh_warn_no_backups(mock_which, mock_run):
    mock_which.return_value = "/usr/bin/kubectl"
    mock_run.return_value = _proc(0, json.dumps({"items": []}))
    pf = preflight.Preflight(_args())
    pf.check_velero_backup_fresh()
    assert pf.checks[-1]["status"] == "warn"


# ── run_all wires everything ───────────────────────────────────────────────


def test_parse_sops_double_encrypt_clean_returns_empty_list():
    decrypted = """
ssh_public_key: ssh-ed25519 AAAA...
k3s_token: K10abcdef::server::secret
tailscale_auth_key: tskey-abc123
tailscale_api_key: tskey-api-def456
"""
    assert preflight.parse_sops_double_encrypt(decrypted) == []


def test_parse_sops_double_encrypt_detects_enc_prefix():
    decrypted = """
ssh_public_key: ENC[AES256_GCM,data:abc==,type:str]
k3s_token: K10normaltoken
tailscale_auth_key: ENC[AES256_GCM,data:xyz==,type:str]
tailscale_api_key: tskey-good
"""
    bad = preflight.parse_sops_double_encrypt(decrypted)
    assert set(bad) == {"ssh_public_key", "tailscale_auth_key"}


def test_parse_sops_double_encrypt_handles_empty_and_invalid_yaml():
    assert preflight.parse_sops_double_encrypt("") == []
    assert preflight.parse_sops_double_encrypt("not: yaml: ::") == []


def test_parse_sops_double_encrypt_ignores_missing_fields():
    """Fields not present in the file shouldn't trigger false positives."""
    decrypted = "ssh_public_key: ssh-ed25519 AAAA...\n"
    assert preflight.parse_sops_double_encrypt(decrypted) == []


def test_check_sops_decrypt_fails_on_double_encrypt(monkeypatch, tmp_path):
    canary = tmp_path / "tf.sops.yaml"
    canary.write_text("dummy: encrypted")
    monkeypatch.setattr(preflight, "SOPS_CANARY", canary)
    pf = preflight.Preflight(_args(skip_aws=True, skip_ssh=True))
    fake_decrypt = MagicMock()
    fake_decrypt.returncode = 0
    fake_decrypt.stdout = "ssh_public_key: ENC[AES256_GCM,data:foo==]\n"
    with patch("preflight.shutil.which", return_value="/usr/bin/sops"), patch.object(
        pf, "run", return_value=fake_decrypt
    ):
        pf.check_sops_decrypt()
    assert pf.checks[-1]["status"] == "fail"
    assert "double-encrypted" in pf.checks[-1]["message"]
    assert "ssh_public_key" in pf.checks[-1]["message"]


def test_check_git_deploy_key_pass(monkeypatch, tmp_path):
    key = tmp_path / "homelab-deploy-key"
    key.write_text("dummy private key")
    monkeypatch.setattr(preflight, "GIT_DEPLOY_KEY_PATH", key)
    pf = preflight.Preflight(_args(skip_aws=True, skip_ssh=True))
    pf.check_git_deploy_key()
    assert pf.checks[-1]["status"] == "pass"


def test_check_git_deploy_key_fail_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "GIT_DEPLOY_KEY_PATH", tmp_path / "nope-key")
    pf = preflight.Preflight(_args(skip_aws=True, skip_ssh=True))
    pf.check_git_deploy_key()
    assert pf.checks[-1]["status"] == "fail"
    assert "ssh-keygen" in pf.checks[-1]["message"]


def test_check_git_deploy_key_fail_empty(monkeypatch, tmp_path):
    key = tmp_path / "empty-key"
    key.write_text("")
    monkeypatch.setattr(preflight, "GIT_DEPLOY_KEY_PATH", key)
    pf = preflight.Preflight(_args(skip_aws=True, skip_ssh=True))
    pf.check_git_deploy_key()
    assert pf.checks[-1]["status"] == "fail"
    assert "empty" in pf.checks[-1]["message"]


def test_run_all_includes_new_checks(monkeypatch, tmp_path):
    """All four new checks must be registered in run_all() — regression guard.

    We make every external command/file fail or skip gracefully; we just
    want the check *names* to appear. This is the canary that protects
    against someone forgetting to wire a new check into run_all().
    """
    monkeypatch.setattr(preflight, "SOPS_CANARY", tmp_path / "nope.yaml")
    monkeypatch.setattr(preflight, "ANSIBLE_INVENTORY", tmp_path / "nope.yml")
    monkeypatch.setattr(preflight, "GIT_DEPLOY_KEY_PATH", tmp_path / "nope-key")

    pf = preflight.Preflight(_args(skip_aws=True, skip_ssh=True))
    # Stub external probes so check_tailscale_key_expiry / cni / velero
    # don't blow up — they should record skip/warn and continue.
    with patch("preflight.shutil.which", return_value=None):
        pf.run_all()
    names = {c["name"] for c in pf.checks}
    assert "aws.quota" in names
    assert "tailscale.key_expiry" in names
    assert "cluster.cni_ready" in names
    assert "velero.backup_fresh" in names
    assert "git.deploy_key" in names
