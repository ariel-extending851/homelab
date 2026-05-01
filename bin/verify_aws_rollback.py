#!/usr/bin/env python3
"""Verifies that `terraform destroy` actually removed homelab resources.

`terraform destroy` can return 0 with stuck ENIs, IAM races, or partially
orphaned resources. This script asserts ground truth via boto3 for the
resource classes Terraform manages directly:

  1. EC2 instances tagged Project=Lab-DevOps-Pro
  2. ENIs tagged Project=Lab-DevOps-Pro (commonly orphaned by spot termination)
  3. IAM user `homelab-velero` (provisioned by infra/aws/main.tf)
  4. Security groups with name_prefix `hl-k3s-cluster-`

S3 buckets (audit, velero, ssm) are intentionally NOT checked: audit/velero
have force_destroy=false to preserve evidence; ssm has force_destroy=true
but is allowed to outlive a single rollback.

Usage:
  python3 bin/verify_aws_rollback.py [--region us-east-1]

Exit codes:
  0  rollback clean
  1  one or more orphan classes detected (table printed)
"""

from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

PROJECT_TAG = "Lab-DevOps-Pro"
VELERO_USER = "homelab-velero"
SG_PREFIX = "hl-k3s-cluster-"
RUNNING_STATES = ["running", "pending", "stopping", "shutting-down"]


# ── pure helpers (unit-testable via mocked boto3 clients) ───────────────────


def list_running_instances(ec2):
    """Return list of (instance_id, state) for project-tagged instances in
    a non-terminated state."""
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [PROJECT_TAG]},
            {"Name": "instance-state-name", "Values": RUNNING_STATES},
        ]
    )
    return [
        (i["InstanceId"], i["State"]["Name"])
        for r in resp.get("Reservations", [])
        for i in r.get("Instances", [])
    ]


def list_project_enis(ec2):
    """Return list of (eni_id, status, description) for project-tagged ENIs."""
    resp = ec2.describe_network_interfaces(
        Filters=[{"Name": "tag:Project", "Values": [PROJECT_TAG]}]
    )
    return [
        (eni["NetworkInterfaceId"], eni.get("Status", ""), eni.get("Description", ""))
        for eni in resp.get("NetworkInterfaces", [])
    ]


def velero_user_exists(iam):
    """True if the velero IAM user is still present. Catches NoSuchEntity."""
    try:
        iam.get_user(UserName=VELERO_USER)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            return False
        raise
    return True


def list_cluster_security_groups(ec2):
    """Return list of (sg_id, name) for SGs whose name starts with SG_PREFIX."""
    resp = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [f"{SG_PREFIX}*"]}]
    )
    return [(sg["GroupId"], sg["GroupName"]) for sg in resp.get("SecurityGroups", [])]


# ── reporting ──────────────────────────────────────────────────────────────


def _print_table(rows, headers):
    if not rows:
        return
    widths = [
        max(len(str(h)), max(len(str(r[i])) for r in rows))
        for i, h in enumerate(headers)
    ]
    sep = "+".join("-" * (w + 2) for w in widths)
    fmt = "|".join(f" {{:<{w}}} " for w in widths)
    print(sep)
    print(fmt.format(*headers))
    print(sep)
    for r in rows:
        print(fmt.format(*[str(c) for c in r]))
    print(sep)


def check(ec2, iam):
    """Run all four checks; return number of orphan classes detected."""
    errors = 0

    print(f"→ Checking EC2 instances tagged Project={PROJECT_TAG}...")
    instances = list_running_instances(ec2)
    if instances:
        print(f"  ❌ {len(instances)} instance(s) still exist:")
        _print_table(instances, ["InstanceId", "State"])
        errors += 1
    else:
        print("  ✅ 0 instances")

    print(f"→ Checking orphaned ENIs tagged Project={PROJECT_TAG}...")
    enis = list_project_enis(ec2)
    if enis:
        print(
            f"  ❌ {len(enis)} ENI(s) still exist (likely orphaned by spot termination):"
        )
        _print_table(enis, ["NetworkInterfaceId", "Status", "Description"])
        errors += 1
    else:
        print("  ✅ 0 ENIs")

    print(f"→ Checking IAM user {VELERO_USER}...")
    if velero_user_exists(iam):
        print(
            f"  ❌ IAM user {VELERO_USER} still exists (Terraform destroy did not remove it)"
        )
        errors += 1
    else:
        print("  ✅ IAM user removed")

    print(f"→ Checking security groups with prefix {SG_PREFIX}...")
    sgs = list_cluster_security_groups(ec2)
    if sgs:
        print(f"  ❌ {len(sgs)} security group(s) still exist:")
        _print_table(sgs, ["GroupId", "GroupName"])
        errors += 1
    else:
        print("  ✅ 0 security groups")

    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region", default="us-east-1", help="AWS region (default: us-east-1)"
    )
    args = parser.parse_args(argv)

    ec2 = boto3.client("ec2", region_name=args.region)
    iam = boto3.client("iam")  # IAM is global; region irrelevant

    errors = check(ec2, iam)

    if errors:
        print()
        print(f"❌ Rollback incomplete: {errors} resource class(es) have orphans.")
        print("   Manual cleanup required — see output above.")
        return 1

    print()
    print("✅ Rollback verified: EC2, ENI, IAM, SG all clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
