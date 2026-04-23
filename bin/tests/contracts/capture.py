#!/usr/bin/env python3
"""Manual contract fixture capture — regenerates golden files from real CLIs.

Gated behind CAPTURE_CONTRACTS=1 to prevent accidental runs. Run against a
live cluster + AWS account when upgrading a tool to refresh snapshots.

Usage:
  CAPTURE_CONTRACTS=1 python3 bin/tests/contracts/capture.py [--section ssm|ec2|terraform|tailscale|kubectl]
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parent


def _require_env():
    if os.environ.get("CAPTURE_CONTRACTS") != "1":
        print("Refusing to run. Set CAPTURE_CONTRACTS=1 to acknowledge.")
        sys.exit(2)


def _write(rel, content):
    p = CONTRACTS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  ✓ {p.relative_to(CONTRACTS)}")


def _run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.stdout, r.returncode


def capture_ssm(instance_id):
    out, _ = _run(
        [
            "aws",
            "ssm",
            "describe-instance-information",
            "--filters",
            f"Key=InstanceIds,Values={instance_id}",
            "--query",
            "InstanceInformationList[0].PingStatus",
            "--output",
            "text",
        ]
    )
    _write("aws_ssm/describe-instance-information--online.txt", out)


def capture_ec2():
    out, _ = _run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--filters",
            "Name=tag:Name,Values=hl-k3s-server",
            "Name=instance-state-name,Values=pending,running",
            "--query",
            "Reservations[0].Instances[0].InstanceId",
            "--output",
            "text",
        ]
    )
    _write("aws_ec2/describe-instances--instance-id.txt", out)


def capture_terraform(terraform_dir="infra/aws"):
    out, _ = _run(["terraform", "output", "-json"], cwd=terraform_dir)
    _write("terraform/output-json--full.json", out)
    out, _ = _run(["terraform", "state", "list"], cwd=terraform_dir)
    _write("terraform/state-list--with-acl.txt", out)


def capture_tailscale():
    out, _ = _run(["tailscale", "status", "--json"])
    _write("tailscale/status--json.json", out)
    out, _ = _run(["tailscale", "ip", "-4"])
    _write("tailscale/ip--connected.txt", out)


def capture_kubectl(kubeconfig=None):
    env = {"KUBECONFIG": kubeconfig} if kubeconfig else {}
    out, _ = _run(["kubectl", "get", "applications", "-n", "argocd", "-o", "json"])
    _write("kubectl/get-applications--json.json", out)
    out, _ = _run(["kubectl", "get", "pods", "-A", "--no-headers"])
    _write("kubectl/get-pods--no-headers.txt", out)
    out, _ = _run(["kubectl", "get", "pvc", "-A", "--no-headers"])
    _write("kubectl/get-pvc--no-headers.txt", out)
    out, _ = _run(["kubectl", "get", "statefulset", "-A", "--no-headers"])
    _write("kubectl/get-statefulset--no-headers.txt", out)


def main():
    _require_env()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--section",
        choices=["ssm", "ec2", "terraform", "tailscale", "kubectl", "all"],
        default="all",
    )
    parser.add_argument("--instance-id", help="Required for --section ssm")
    parser.add_argument("--terraform-dir", default="infra/aws")
    args = parser.parse_args()

    if args.section in ("ec2", "all"):
        capture_ec2()
    if args.section in ("ssm", "all"):
        if not args.instance_id:
            print("--instance-id required for ssm capture")
            sys.exit(2)
        capture_ssm(args.instance_id)
    if args.section in ("terraform", "all"):
        capture_terraform(args.terraform_dir)
    if args.section in ("tailscale", "all"):
        capture_tailscale()
    if args.section in ("kubectl", "all"):
        capture_kubectl()


if __name__ == "__main__":
    main()
