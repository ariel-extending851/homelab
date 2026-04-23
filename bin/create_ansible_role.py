#!/usr/bin/env python3
"""Create new Ansible role from template scaffold.

Port of scripts/create-ansible-role.sh — preserves validation rules,
exit codes, placeholder-substitution list, and next-step instructions.

Usage:
  python3 bin/create_ansible_role.py my_new_role
  make new-role ROLE=my_new_role
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

ROLE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
PLACEHOLDER = "[ROLE_NAME]"

# Files inside the generated role that receive [ROLE_NAME] substitution.
# Mirrors the exact list from the original shell script.
PLACEHOLDER_FILES = [
    "meta/main.yml",
    "README.md",
    "molecule/default/molecule.yml",
    "molecule/default/converge.yml",
    "molecule/default/verify.yml",
]


def validate_role_name(role_name):
    return bool(role_name) and bool(ROLE_NAME_PATTERN.match(role_name))


def create_role(role_name, base_dir):
    """Create Ansible role scaffold at base_dir/ansible/roles/{role_name}.

    Returns 0 on success, 1 on validation/state error.
    """
    if not role_name:
        print("Usage: create_ansible_role.py <role_name>", file=sys.stderr)
        return 1

    if not validate_role_name(role_name):
        print(f"❌ Invalid role name: '{role_name}'", file=sys.stderr)
        print(
            "   Use only alphanumeric characters and underscores",
            file=sys.stderr,
        )
        return 1

    role_path = base_dir / "ansible" / "roles" / role_name
    # User-facing paths are displayed relative to repo root, matching the
    # original shell script output ("ansible/roles/<name>") rather than
    # absolute paths derived from Path.cwd().
    role_display = f"ansible/roles/{role_name}"
    template_display = "ansible/roles/.template"

    if role_path.exists():
        print(
            f"❌ Role '{role_name}' already exists at {role_display}",
            file=sys.stderr,
        )
        return 1

    template_path = base_dir / "ansible" / "roles" / ".template"
    if not template_path.is_dir():
        print(f"❌ Template not found at {template_display}", file=sys.stderr)
        print(
            "   Make sure you're running from the repository root",
            file=sys.stderr,
        )
        return 1

    shutil.copytree(template_path, role_path)
    print(f"✅ Role structure created at {role_display}")

    print("🔄 Updating placeholders...")
    for relpath in PLACEHOLDER_FILES:
        target = role_path / relpath
        if target.is_file():
            target.write_text(
                target.read_text(encoding="utf-8").replace(PLACEHOLDER, role_name),
                encoding="utf-8",
            )

    _print_next_steps(role_name, role_display)
    return 0


def _print_next_steps(role_name, role_path):
    print()
    print("✅ Role created successfully!")
    print()
    print("📋 Next steps:")
    print()
    print("1. Edit your role's defaults:")
    print(f"   vim {role_path}/defaults/main.yml")
    print()
    print("2. Implement the role logic:")
    print(f"   vim {role_path}/tasks/main.yml")
    print()
    print("3. Update Molecule test setup (pre_tasks, stubs, etc):")
    print(f"   vim {role_path}/molecule/default/converge.yml")
    print()
    print("4. Add test assertions:")
    print(f"   vim {role_path}/molecule/default/verify.yml")
    print()
    print("5. Test locally:")
    print(f"   make test-molecule-{role_name}")
    print()
    print("6. Validate structure:")
    print("   make validate-ansible-structure")
    print()
    print("📚 For more details:")
    print("   - Read: CONTRIBUTING.md")
    print("   - Reference: ansible/roles/tailscale/ (simple) or k3s/ (complex)")
    print("   - Checklist: docs/contributing/role-template.md")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create a new Ansible role from the template scaffold.",
    )
    parser.add_argument(
        "role_name",
        nargs="?",
        help="Role name (alphanumeric + underscore only)",
    )
    args = parser.parse_args(argv)

    if args.role_name is None:
        print("Usage: create_ansible_role.py <role_name>", file=sys.stderr)
        return 1

    return create_role(args.role_name, base_dir=Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
