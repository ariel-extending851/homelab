#!/usr/bin/env python3
"""Create new Ansible role from the Copier template at templates/ansible-role/.

This is a thin wrapper around `copier copy` that preserves the original CLI
contract (`make new-role ROLE=name`) so existing muscle memory keeps working.
The role-name regex and exit codes mirror the previous implementation.

Usage:
  python3 bin/create_ansible_role.py my_new_role
  make new-role ROLE=my_new_role
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROLE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
TEMPLATE_SUBPATH = Path("templates") / "ansible-role"


def validate_role_name(role_name):
    return bool(role_name) and bool(ROLE_NAME_PATTERN.match(role_name))


def _resolve_copier(env_override=None):
    """Locate the copier binary. Prefer mise-managed, fall back to PATH."""
    if env_override:
        return env_override
    found = shutil.which("copier")
    if found:
        return found
    # mise exec fallback — works inside the repo even if PATH isn't fully set up.
    if shutil.which("mise"):
        return ["mise", "exec", "--", "copier"]
    return None


def create_role(role_name, base_dir, copier_runner=None):
    """Render the Copier template at base_dir/ansible/roles/{role_name}.

    Returns 0 on success, 1 on validation/state error, 2 if copier missing.
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
    role_display = f"ansible/roles/{role_name}"
    template_path = base_dir / TEMPLATE_SUBPATH

    if role_path.exists():
        print(
            f"❌ Role '{role_name}' already exists at {role_display}",
            file=sys.stderr,
        )
        return 1

    if not template_path.is_dir():
        print(f"❌ Template not found at {TEMPLATE_SUBPATH}", file=sys.stderr)
        print(
            "   Make sure you're running from the repository root",
            file=sys.stderr,
        )
        return 1

    runner = copier_runner if copier_runner is not None else _resolve_copier()
    if runner is None:
        print(
            "❌ `copier` not found. Run `mise install` (it's in .mise.toml).",
            file=sys.stderr,
        )
        return 2

    cmd = list(runner) if isinstance(runner, list) else [runner]
    cmd += [
        "copy",
        "--defaults",
        "--data",
        f"role_name={role_name}",
        "--vcs-ref=HEAD",
        "--quiet",
        str(template_path),
        str(role_path),
    ]

    result = subprocess.run(cmd, cwd=base_dir)
    if result.returncode != 0:
        print(
            f"❌ copier failed (exit {result.returncode}). See output above.",
            file=sys.stderr,
        )
        return result.returncode

    print(f"✅ Role structure created at {role_display}")
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
        description="Create a new Ansible role from the Copier template.",
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
