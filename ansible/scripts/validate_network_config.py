#!/usr/bin/env python3
"""Validate network topology configuration before deployment.

Port of ansible/scripts/validate_network_config.sh. Performs six static
checks against inventory, group_vars, the gatekeeper role, and the router
playbook; optionally runs ansible-playbook --syntax-check if ansible is
installed on PATH.
"""

import shutil
import subprocess
import sys
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
NC = "\033[0m"


INVENTORY_IPS = [
    "ansible_host: 192.168.8.11",
    "ansible_host: 192.168.8.12",
    "ansible_host: 192.168.8.120",
    "ansible_host: 192.168.8.1",
]

GROUP_VARS_MARKERS = [
    'network_cidr: "192.168.8.0/24"',
    'guest_network_cidr: "192.168.9.0/24"',
    'gateway_ip: "192.168.8.1"',
]

ZERO_TRUST_MARKERS = ["block_guest_to_admin", "guest_network_cidr"]
WAN_DHCP_MARKERS = [
    "Configure WAN interface for DHCP",
    "network.wan.proto='dhcp'",
]


def print_ok(message):
    print(f"{GREEN}✓{NC} {message}")


def print_fail(message):
    print(f"{RED}✗{NC} {message}")


def print_skip(message):
    print(f"{YELLOW}⚠{NC} {message}")


def file_contains_all(path, needles):
    """Return True iff every string in needles is found in the file."""
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8")
    return all(needle in content for needle in needles)


def _check_contains(label_ok, label_fail, path, needles):
    if file_contains_all(path, needles):
        print_ok(label_ok)
        return 0
    print_fail(label_fail)
    return 1


def validate(ansible_root):
    """Run all static checks. Returns number of failed checks."""
    errors = 0
    inventory = ansible_root / "inventory" / "production.yml"
    group_vars = ansible_root / "group_vars" / "all.yml"
    gatekeeper_tasks = ansible_root / "roles" / "gatekeeper" / "tasks" / "main.yml"
    router_playbook = ansible_root / "playbooks" / "configure_router.yml"

    print("→ Validating inventory file...")
    errors += _check_contains(
        "All hosts have correct IP addresses",
        "Missing or incorrect IP addresses in inventory",
        inventory,
        INVENTORY_IPS,
    )

    print("→ Validating global variables...")
    errors += _check_contains(
        "Network topology variables defined correctly",
        "Missing or incorrect network topology variables",
        group_vars,
        GROUP_VARS_MARKERS,
    )

    print("→ Validating gatekeeper role...")
    errors += _check_contains(
        "Zero Trust isolation rule present",
        "Zero Trust isolation rule missing",
        gatekeeper_tasks,
        ZERO_TRUST_MARKERS,
    )

    print("→ Validating WAN DHCP configuration...")
    errors += _check_contains(
        "WAN DHCP configuration present",
        "WAN DHCP configuration missing",
        gatekeeper_tasks,
        WAN_DHCP_MARKERS,
    )

    print("→ Validating router playbook...")
    if router_playbook.is_file():
        print_ok("Router playbook exists")
    else:
        print_fail("Router playbook missing")
        errors += 1

    if shutil.which("ansible-playbook"):
        print("→ Checking Ansible syntax...")
        try:
            subprocess.run(
                ["ansible-playbook", "--syntax-check", str(router_playbook)],
                capture_output=True,
                check=True,
            )
            print_ok("Ansible playbook syntax valid")
        except subprocess.CalledProcessError:
            print_fail("Ansible playbook has syntax errors")
            errors += 1
    else:
        print_skip("Ansible not installed, skipping syntax check")

    return errors


def main():
    print("=================================================")
    print("Network Configuration Validation")
    print("=================================================")
    print()

    script_dir = Path(__file__).resolve().parent
    ansible_root = script_dir.parent

    errors = validate(ansible_root)

    print()
    print("=================================================")
    if errors == 0:
        print(f"{GREEN}All validation checks passed!{NC}")
        print()
        print("Next steps:")
        print("  1. Test with dry-run:")
        print(
            "     ansible-playbook -i inventory/production.yml "
            "playbooks/configure_router.yml --check"
        )
        print()
        print("  2. Apply configuration:")
        print(
            "     ansible-playbook -i inventory/production.yml "
            "playbooks/configure_router.yml"
        )
        print()
        return 0

    print(f"{RED}Validation failed with {errors} error(s){NC}")
    print("Please fix the issues above before proceeding.")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
