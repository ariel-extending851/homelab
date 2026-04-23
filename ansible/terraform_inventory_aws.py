#!/usr/bin/env python3
"""
Ansible Dynamic Inventory Script for AWS Terraform-managed k3s Infrastructure

This script reads Terraform outputs from the AWS infrastructure and generates
an Ansible-compatible dynamic inventory in JSON format.

Usage:
    ./terraform_inventory_aws.py --list
    ./terraform_inventory_aws.py --host <hostname>

Requirements:
    - Terraform state must be initialized in ../infra/aws/
    - Python 3.6+
    - Terraform CLI installed and in PATH

Reference:
    https://docs.ansible.com/ansible/latest/dev_guide/developing_inventory.html
"""

import json
import subprocess
import sys
import os
from pathlib import Path


# ── parsing helpers (pure functions — contract-testable) ────────────────────


def parse_terraform_output_json(stdout):
    """Parse `terraform output -json` stdout into a flat dict {name: value}.

    Strips Terraform's `{"value": ..., "type": ...}` wrapper. Missing keys
    become empty strings so downstream `.get()` chains are simpler.
    Raises json.JSONDecodeError if stdout is not valid JSON.
    """
    raw = json.loads(stdout or "{}")
    return {k: v.get("value", "") if isinstance(v, dict) else v for k, v in raw.items()}


def parse_tailscale_status_json(stdout):
    """Parse `tailscale status --json` into {hostname: ipv4} for ONLINE peers only.

    Skips IPv6-only peers and offline peers. Returns {} on any JSON error so the
    inventory can fall back to private IPs.
    """
    try:
        data = json.loads(stdout or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    ips = {}
    for peer in (data.get("Peer") or {}).values():
        hostname = peer.get("HostName", "")
        tailscale_ips = peer.get("TailscaleIPs", [])
        if hostname and tailscale_ips and peer.get("Online", False):
            ipv4 = next((ip for ip in tailscale_ips if ":" not in ip), None)
            if ipv4:
                ips[hostname] = ipv4
    return ips


class TerraformInventoryAWS:
    """Generate Ansible inventory from Terraform state (AWS)"""

    def __init__(self, terraform_dir: str = "../infra/aws"):
        self.terraform_dir = Path(__file__).parent / terraform_dir
        self.inventory = {
            "_meta": {"hostvars": {}},
            "all": {"children": ["k3s_cluster"]},
            "k3s_cluster": {"children": ["k3s_server", "k3s_agent"]},
            "k3s_server": {"hosts": []},
            "k3s_agent": {"hosts": []},
        }

    def get_terraform_outputs(self) -> dict:
        """Execute terraform output -json and parse results"""
        try:
            result = subprocess.run(
                ["terraform", "output", "-json"],
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return parse_terraform_output_json(result.stdout)
        except subprocess.CalledProcessError as e:
            print(
                f"ERROR: Failed to read Terraform outputs: {e.stderr}", file=sys.stderr
            )
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON from Terraform: {e}", file=sys.stderr)
            sys.exit(1)

    def _get_tailscale_ips(self) -> dict:
        """Return a dict of {tailscale-hostname: tailscale-ipv4} for online peers.

        Uses `tailscale status --json` which is always available locally since
        this machine is itself on the tailnet. Falls back to an empty dict so
        the caller can use private/public IPs as a fallback.
        """
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            return parse_tailscale_status_json(result.stdout)
        except Exception:
            return {}

    def build_inventory(self):
        """Build Ansible inventory from Terraform outputs"""
        outputs = self.get_terraform_outputs()

        # Extract server data
        server_public_ip = outputs.get("k3s_server_public_ip", "")
        server_private_ip = outputs.get("k3s_server_private_ip", "")
        server_instance_id = outputs.get("k3s_server_instance_id", "")

        # Extract agent data
        agent_public_ip = outputs.get("k3s_agent_public_ip", "")
        agent_private_ip = outputs.get("k3s_agent_private_ip", "")
        agent_instance_id = outputs.get("k3s_agent_instance_id", "")

        if not server_instance_id:
            print(
                "ERROR: Missing required Terraform output (k3s_server_instance_id). "
                "Ensure you have run 'terraform apply' in the infra/aws/ directory.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Resolve Tailscale IPs via `tailscale status` — Zero Trust access model.
        # Ansible connects over the private Tailscale mesh, not public internet.
        # Public IPs are retained as metadata only (no public SSH ingress).
        tailscale_ips = self._get_tailscale_ips()
        server_tailscale_ip = tailscale_ips.get("k3s-server-1", server_private_ip)
        agent_tailscale_ip = tailscale_ips.get("k3s-agent-2", agent_private_ip)

        # SSM configuration from environment variables (set by Terraform or CI/CD)
        SSM_BUCKET = os.environ.get("ANSIBLE_AWS_SSM_BUCKET_NAME", "")
        SSM_REGION = os.environ.get(
            "ANSIBLE_AWS_SSM_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )

        if not SSM_BUCKET:
            print(
                "WARNING: ANSIBLE_AWS_SSM_BUCKET_NAME environment variable not set. "
                "Ansible SSM connection may fail. Set it to the S3 bucket used for SSM Session Manager.",
                file=sys.stderr,
            )

        # Add k3s server — connect via SSM (Zero Trust, no SSH keys required)
        server_hostname = "k3s-server"
        self.inventory["k3s_server"]["hosts"].append(server_hostname)
        self.inventory["_meta"]["hostvars"][server_hostname] = {
            "ansible_host": server_instance_id,
            "ansible_connection": "amazon.aws.aws_ssm",
            "ansible_aws_ssm_region": SSM_REGION,
            "ansible_aws_ssm_bucket_name": SSM_BUCKET,
            "ansible_remote_tmp": "/tmp/ansible-ssm",
            "ansible_user": "ec2-user",
            "private_ip": server_private_ip,
            "public_ip": server_public_ip,
            "tailscale_ip": server_tailscale_ip,
            "instance_id": server_instance_id,
            "node_type": "server",
            "k3s_control_node": True,
        }

        # Add k3s agent — connect via SSM (Zero Trust, no SSH keys required)
        if agent_instance_id:
            agent_hostname = "k3s-agent"
            self.inventory["k3s_agent"]["hosts"].append(agent_hostname)
            self.inventory["_meta"]["hostvars"][agent_hostname] = {
                "ansible_host": agent_instance_id,
                "ansible_connection": "amazon.aws.aws_ssm",
                "ansible_aws_ssm_region": SSM_REGION,
                "ansible_aws_ssm_bucket_name": SSM_BUCKET,
                "ansible_remote_tmp": "/tmp/ansible-ssm",
                "ansible_user": "ec2-user",
                "private_ip": agent_private_ip,
                "public_ip": agent_public_ip,
                "tailscale_ip": agent_tailscale_ip,
                "instance_id": agent_instance_id,
                "node_type": "agent",
                "k3s_control_node": False,
            }

    def get_host(self, hostname: str) -> dict:
        """Return variables for a specific host"""
        self.build_inventory()
        return self.inventory["_meta"]["hostvars"].get(hostname, {})

    def list_inventory(self) -> dict:
        """Return the full inventory"""
        self.build_inventory()
        return self.inventory


def main():
    """Main entry point for Ansible dynamic inventory"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Terraform-based Ansible Dynamic Inventory for AWS"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all hosts in inventory (Ansible standard)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Get variables for a specific host (Ansible standard)",
    )
    parser.add_argument(
        "--terraform-dir",
        type=str,
        default=os.environ.get("TF_DIR", "../infra/aws"),
        help="Path to Terraform directory (default: ../infra/aws, or TF_DIR env var)",
    )
    parser.add_argument(
        "--ssm-bucket",
        type=str,
        default=os.environ.get("ANSIBLE_AWS_SSM_BUCKET_NAME", ""),
        help="S3 bucket for SSM Session Manager (default: ANSIBLE_AWS_SSM_BUCKET_NAME env var)",
    )
    parser.add_argument(
        "--ssm-region",
        type=str,
        default=os.environ.get(
            "ANSIBLE_AWS_SSM_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        ),
        help="AWS region for SSM (default: ANSIBLE_AWS_SSM_REGION or AWS_DEFAULT_REGION env var)",
    )

    args = parser.parse_args()

    # Override environment variables with command-line arguments if provided
    if args.ssm_bucket:
        os.environ["ANSIBLE_AWS_SSM_BUCKET_NAME"] = args.ssm_bucket
    if args.ssm_region:
        os.environ["ANSIBLE_AWS_SSM_REGION"] = args.ssm_region

    inventory = TerraformInventoryAWS(terraform_dir=args.terraform_dir)

    if args.list:
        print(json.dumps(inventory.list_inventory(), indent=2))
    elif args.host:
        print(json.dumps(inventory.get_host(args.host), indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
