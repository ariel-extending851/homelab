"""
Unit tests for ansible/terraform_inventory_aws.py

Tests the inventory builder with mocked subprocess calls — no real Terraform
or Tailscale required. Covers: happy path (server + agent), server-only,
missing instance ID exit, Tailscale IP preference, fallback to private IP,
--host query, and empty outputs guard.
"""

import json
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow import from the parent ansible/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
import terraform_inventory_aws as inv_module
from terraform_inventory_aws import TerraformInventoryAWS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_OUTPUTS = {
    "k3s_server_instance_id": {"value": "i-server123"},
    "k3s_server_private_ip": {"value": "10.0.1.10"},
    "k3s_server_public_ip": {"value": "54.1.2.3"},
    "k3s_agent_instance_id": {"value": "i-agent456"},
    "k3s_agent_private_ip": {"value": "10.0.1.20"},
    "k3s_agent_public_ip": {"value": "54.4.5.6"},
}

SERVER_ONLY_OUTPUTS = {
    "k3s_server_instance_id": {"value": "i-server123"},
    "k3s_server_private_ip": {"value": "10.0.1.10"},
    "k3s_server_public_ip": {"value": "54.1.2.3"},
    "k3s_agent_instance_id": {"value": ""},
    "k3s_agent_private_ip": {"value": ""},
    "k3s_agent_public_ip": {"value": ""},
}

TAILSCALE_STATUS = {
    "Peer": {
        "peer-key-1": {
            "HostName": "k3s-server-1",
            "TailscaleIPs": ["100.64.0.1", "fd7a::1"],
            "Online": True,
        },
        "peer-key-2": {
            "HostName": "k3s-agent-2",
            "TailscaleIPs": ["100.64.0.2", "fd7a::2"],
            "Online": True,
        },
    }
}


def _make_inventory(outputs=None, tailscale=None, env=None):
    """Return a TerraformInventoryAWS with mocked subprocess."""
    tf_out = outputs if outputs is not None else MINIMAL_OUTPUTS
    ts_data = tailscale if tailscale is not None else {}

    def _fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if "terraform" in cmd:
            result.stdout = json.dumps(tf_out)
        elif "tailscale" in cmd:
            if ts_data:
                result.stdout = json.dumps(ts_data)
            else:
                raise FileNotFoundError("tailscale not found")
        return result

    extra_env = env or {}
    with patch.dict(
        os.environ, {"ANSIBLE_AWS_SSM_BUCKET_NAME": "test-bucket", **extra_env}
    ):
        with patch("subprocess.run", side_effect=_fake_run):
            inventory = TerraformInventoryAWS(terraform_dir=".")
            inventory.build_inventory()
    return inventory


# ---------------------------------------------------------------------------
# Tests: inventory structure
# ---------------------------------------------------------------------------


def test_inventory_groups_present():
    inv = _make_inventory()
    assert "k3s_server" in inv.inventory
    assert "k3s_agent" in inv.inventory
    assert "k3s_cluster" in inv.inventory


def test_server_host_added():
    inv = _make_inventory()
    assert "k3s-server" in inv.inventory["k3s_server"]["hosts"]


def test_agent_host_added_when_present():
    inv = _make_inventory()
    assert "k3s-agent" in inv.inventory["k3s_agent"]["hosts"]


def test_agent_host_absent_when_instance_id_empty():
    inv = _make_inventory(outputs=SERVER_ONLY_OUTPUTS)
    assert inv.inventory["k3s_agent"]["hosts"] == []


def test_server_hostvars_contain_required_keys():
    inv = _make_inventory()
    hostvars = inv.inventory["_meta"]["hostvars"]["k3s-server"]
    for key in (
        "ansible_host",
        "ansible_connection",
        "instance_id",
        "private_ip",
        "node_type",
        "k3s_control_node",
    ):
        assert key in hostvars, f"Missing key: {key}"


def test_server_is_control_node():
    inv = _make_inventory()
    assert inv.inventory["_meta"]["hostvars"]["k3s-server"]["k3s_control_node"] is True


def test_agent_is_not_control_node():
    inv = _make_inventory()
    assert inv.inventory["_meta"]["hostvars"]["k3s-agent"]["k3s_control_node"] is False


def test_ansible_host_is_instance_id():
    inv = _make_inventory()
    assert (
        inv.inventory["_meta"]["hostvars"]["k3s-server"]["ansible_host"]
        == "i-server123"
    )


# ---------------------------------------------------------------------------
# Tests: Tailscale IP resolution
# ---------------------------------------------------------------------------


def test_tailscale_ip_used_when_online():
    inv = _make_inventory(tailscale=TAILSCALE_STATUS)
    assert (
        inv.inventory["_meta"]["hostvars"]["k3s-server"]["tailscale_ip"] == "100.64.0.1"
    )
    assert (
        inv.inventory["_meta"]["hostvars"]["k3s-agent"]["tailscale_ip"] == "100.64.0.2"
    )


def test_tailscale_fallback_to_private_ip_when_unavailable():
    inv = _make_inventory(tailscale=None)  # tailscale raises FileNotFoundError
    assert (
        inv.inventory["_meta"]["hostvars"]["k3s-server"]["tailscale_ip"] == "10.0.1.10"
    )
    assert (
        inv.inventory["_meta"]["hostvars"]["k3s-agent"]["tailscale_ip"] == "10.0.1.20"
    )


def test_tailscale_offline_peer_ignored():
    ts_offline = {
        "Peer": {
            "peer-key-1": {
                "HostName": "k3s-server-1",
                "TailscaleIPs": ["100.64.0.1"],
                "Online": False,  # offline
            },
        }
    }
    inv = _make_inventory(tailscale=ts_offline)
    # offline peer → falls back to private IP
    assert (
        inv.inventory["_meta"]["hostvars"]["k3s-server"]["tailscale_ip"] == "10.0.1.10"
    )


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


def test_missing_server_instance_id_exits():
    bad_outputs = {**MINIMAL_OUTPUTS, "k3s_server_instance_id": {"value": ""}}
    with pytest.raises(SystemExit) as exc_info:
        _make_inventory(outputs=bad_outputs)
    assert exc_info.value.code == 1


def test_terraform_command_failure_exits():
    def _fail_run(cmd, **kwargs):
        if "terraform" in cmd:
            raise __import__("subprocess").CalledProcessError(
                1, cmd, stderr="state locked"
            )
        return MagicMock(stdout="{}")

    with patch("subprocess.run", side_effect=_fail_run):
        inventory = TerraformInventoryAWS(terraform_dir=".")
        with pytest.raises(SystemExit) as exc_info:
            inventory.build_inventory()
    assert exc_info.value.code == 1


def test_invalid_terraform_json_exits():
    def _bad_json(cmd, **kwargs):
        result = MagicMock()
        result.stdout = "not-valid-json{"
        return result

    with patch("subprocess.run", side_effect=_bad_json):
        inventory = TerraformInventoryAWS(terraform_dir=".")
        with pytest.raises(SystemExit) as exc_info:
            inventory.build_inventory()
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Tests: --host query
# ---------------------------------------------------------------------------


def test_get_host_returns_server_vars():
    def _fake_run(cmd, **kwargs):
        result = MagicMock()
        if "terraform" in cmd:
            result.stdout = json.dumps(MINIMAL_OUTPUTS)
        else:
            raise FileNotFoundError
        return result

    with patch.dict(os.environ, {"ANSIBLE_AWS_SSM_BUCKET_NAME": "test-bucket"}):
        with patch("subprocess.run", side_effect=_fake_run):
            inventory = TerraformInventoryAWS(terraform_dir=".")
            hostvars = inventory.get_host("k3s-server")

    assert hostvars["instance_id"] == "i-server123"
    assert hostvars["k3s_control_node"] is True


def test_get_host_returns_empty_for_unknown_host():
    def _fake_run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = json.dumps(MINIMAL_OUTPUTS)
        if "tailscale" in cmd:
            raise FileNotFoundError
        return result

    with patch.dict(os.environ, {"ANSIBLE_AWS_SSM_BUCKET_NAME": "test-bucket"}):
        with patch("subprocess.run", side_effect=_fake_run):
            inventory = TerraformInventoryAWS(terraform_dir=".")
            hostvars = inventory.get_host("no-such-host")

    assert hostvars == {}


# ---------------------------------------------------------------------------
# Tests: SSM connection config
# ---------------------------------------------------------------------------


def test_ssm_bucket_set_from_environment():
    inv = _make_inventory(env={"ANSIBLE_AWS_SSM_BUCKET_NAME": "my-ssm-bucket"})
    hostvars = inv.inventory["_meta"]["hostvars"]["k3s-server"]
    assert hostvars["ansible_aws_ssm_bucket_name"] == "my-ssm-bucket"


def test_ssm_connection_type_is_aws_ssm():
    inv = _make_inventory()
    hostvars = inv.inventory["_meta"]["hostvars"]["k3s-server"]
    assert hostvars["ansible_connection"] == "amazon.aws.aws_ssm"
