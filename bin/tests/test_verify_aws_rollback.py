"""Tests for bin/verify_aws_rollback.py.

Mocks boto3 client method calls and asserts the script's exit code +
the orphan classes it surfaces. Mirrors the 6 scenarios that the
predecessor bats suite covered.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verify_aws_rollback as r  # noqa: E402


# ── client builders ─────────────────────────────────────────────────────────


def make_ec2(*, instances=0, enis=0, sgs=0):
    """Build a MagicMock EC2 client returning the given counts."""
    client = MagicMock()
    client.describe_instances.return_value = {
        "Reservations": [
            {"Instances": [{"InstanceId": f"i-{n:08x}", "State": {"Name": "running"}}]}
            for n in range(instances)
        ]
    }
    client.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": f"eni-{n:08x}",
                "Status": "available",
                "Description": "",
            }
            for n in range(enis)
        ]
    }
    client.describe_security_groups.return_value = {
        "SecurityGroups": [
            {"GroupId": f"sg-{n:08x}", "GroupName": f"hl-k3s-cluster-{n}"}
            for n in range(sgs)
        ]
    }
    return client


def make_iam(*, velero_user_exists=False):
    client = MagicMock()
    if velero_user_exists:
        client.get_user.return_value = {"User": {"UserName": r.VELERO_USER}}
    else:
        client.get_user.side_effect = ClientError(
            {"Error": {"Code": "NoSuchEntity", "Message": "user not found"}}, "GetUser"
        )
    return client


# ── happy path ──────────────────────────────────────────────────────────────


def test_clean_rollback_returns_0(capsys):
    rc = r.check(make_ec2(), make_iam())
    assert rc == 0
    captured = capsys.readouterr().out
    assert "0 instances" in captured
    assert "0 ENIs" in captured
    assert "IAM user removed" in captured
    assert "0 security groups" in captured


# ── one orphan class fails the check ────────────────────────────────────────


def test_running_instances_flagged():
    rc = r.check(make_ec2(instances=2), make_iam())
    assert rc == 1


def test_orphan_enis_flagged():
    rc = r.check(make_ec2(enis=3), make_iam())
    assert rc == 1


def test_velero_user_flagged():
    rc = r.check(make_ec2(), make_iam(velero_user_exists=True))
    assert rc == 1


def test_orphan_security_groups_flagged():
    rc = r.check(make_ec2(sgs=1), make_iam())
    assert rc == 1


# ── multiple orphan classes accumulate ──────────────────────────────────────


def test_multiple_orphan_classes(capsys):
    rc = r.check(make_ec2(instances=1, enis=2), make_iam(velero_user_exists=True))
    assert rc == 3
    out = capsys.readouterr().out
    assert "1 instance(s) still exist" in out
    assert "2 ENI(s) still exist" in out
    assert f"IAM user {r.VELERO_USER} still exists" in out


# ── pure helpers ────────────────────────────────────────────────────────────


def test_list_running_instances_empty():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": []}
    assert r.list_running_instances(ec2) == []


def test_list_running_instances_filter_args():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": []}
    r.list_running_instances(ec2)
    args = ec2.describe_instances.call_args.kwargs["Filters"]
    tag_filter = next(f for f in args if f["Name"] == "tag:Project")
    state_filter = next(f for f in args if f["Name"] == "instance-state-name")
    assert tag_filter["Values"] == [r.PROJECT_TAG]
    assert "running" in state_filter["Values"]


def test_velero_user_exists_handles_no_such_entity():
    iam = MagicMock()
    iam.get_user.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": ""}}, "GetUser"
    )
    assert r.velero_user_exists(iam) is False


def test_velero_user_exists_propagates_other_errors():
    iam = MagicMock()
    iam.get_user.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "no perms"}}, "GetUser"
    )
    with pytest.raises(ClientError):
        r.velero_user_exists(iam)


# ── main entrypoint ─────────────────────────────────────────────────────────


def test_main_clean_returns_0(monkeypatch):
    monkeypatch.setattr(
        r.boto3, "client", lambda svc, **kw: make_ec2() if svc == "ec2" else make_iam()
    )
    assert r.main(["--region", "us-east-1"]) == 0


def test_main_dirty_returns_1(monkeypatch):
    def factory(svc, **kw):
        return make_ec2(instances=1) if svc == "ec2" else make_iam()

    monkeypatch.setattr(r.boto3, "client", factory)
    assert r.main([]) == 1
