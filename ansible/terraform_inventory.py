#!/usr/bin/env python3
"""
Ansible Dynamic Inventory Script for Terraform-managed k3s Infrastructure

This script reads Terraform outputs from the OCI infrastructure and generates
an Ansible-compatible dynamic inventory in JSON format.

Usage:
    ./terraform_inventory.py --list
    ./terraform_inventory.py --host <hostname>

Requirements:
    - Terraform state must be initialized in ../infra/oci/
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


class TerraformInventory:
    """Generate Ansible inventory from Terraform state"""

    def __init__(self, terraform_dir: str = "../infra/oci"):
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
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to read Terraform outputs: {e.stderr}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON from Terraform: {e}", file=sys.stderr)
            sys.exit(1)

    def build_inventory(self):
        """Build Ansible inventory from Terraform outputs"""
        outputs = self.get_terraform_outputs()

        # Extract node data from Terraform outputs
        node_names = outputs.get("k3s_node_names", {}).get("value", [])
        public_ips = outputs.get("k3s_node_public_ips", {}).get("value", [])
        private_ips = outputs.get("k3s_node_private_ips", {}).get("value", [])

        if not node_names or not public_ips or not private_ips:
            print(
                "ERROR: Missing required Terraform outputs (k3s_node_names, k3s_node_public_ips, k3s_node_private_ips)",
                file=sys.stderr,
            )
            sys.exit(1)

        if len(node_names) != len(public_ips) or len(node_names) != len(private_ips):
            print(
                "ERROR: Terraform outputs have mismatched lengths",
                file=sys.stderr,
            )
            sys.exit(1)

        # First node is the k3s server (control plane)
        # Remaining nodes are k3s agents
        for idx, (name, public_ip, private_ip) in enumerate(
            zip(node_names, public_ips, private_ips)
        ):
            # Add to appropriate group
            if idx == 0:
                self.inventory["k3s_server"]["hosts"].append(name)
            else:
                self.inventory["k3s_agent"]["hosts"].append(name)

            # Add host variables
            self.inventory["_meta"]["hostvars"][name] = {
                "ansible_host": public_ip,
                "ansible_user": "opc",  # OCI default user
                "private_ip": private_ip,
                "public_ip": public_ip,
                "node_index": idx,
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
        description="Terraform-based Ansible Dynamic Inventory"
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

    args = parser.parse_args()

    inventory = TerraformInventory()

    if args.list:
        print(json.dumps(inventory.list_inventory(), indent=2))
    elif args.host:
        print(json.dumps(inventory.get_host(args.host), indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
