#!/usr/bin/env python3
"""Scaffold a new Kubernetes app under k8s/apps/<name>/ via Copier.

Wraps `copier copy templates/k8s-app/` and performs follow-ups:
  - Validates the kebab-case name (per docs/CONVENTIONS.md §1.2)
  - Refuses to overwrite an existing app directory
  - Registers the app in k8s/apps/kustomization.yaml so ArgoCD picks it up

Usage:
  python3 bin/create_homelab_app.py my-app
  make new-app APP=my-app
"""

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
TEMPLATE_SUBPATH = Path("templates") / "k8s-app"
APPS_SUBPATH = Path("k8s") / "apps"
ROOT_KUSTOMIZATION = APPS_SUBPATH / "kustomization.yaml"


def validate_app_name(name):
    return bool(name) and bool(APP_NAME_PATTERN.match(name))


def _resolve_copier():
    if shutil.which("copier"):
        return ["copier"]
    if shutil.which("mise"):
        return ["mise", "exec", "--", "copier"]
    return None


def register_in_root_kustomization(base_dir, app_name):
    """Append `- ./<app>` to k8s/apps/kustomization.yaml if not already present."""
    root = base_dir / ROOT_KUSTOMIZATION
    if not root.is_file():
        print(
            f"⚠️  {ROOT_KUSTOMIZATION} not found — register the app manually.",
            file=sys.stderr,
        )
        return

    content = root.read_text(encoding="utf-8")
    entry = f"- ./{app_name}"
    if entry in content:
        return

    if content.endswith("\n"):
        content += f"{entry}\n"
    else:
        content += f"\n{entry}\n"
    root.write_text(content, encoding="utf-8")
    print(f"✅ Registered ./{app_name} in {ROOT_KUSTOMIZATION}")


def create_app(app_name, base_dir, copier_runner=None):
    if not app_name:
        print("Usage: create_homelab_app.py <app-name>", file=sys.stderr)
        return 1

    if not validate_app_name(app_name):
        print(f"❌ Invalid app name: '{app_name}'", file=sys.stderr)
        print(
            "   Must be kebab-case: ^[a-z][a-z0-9-]*$ "
            "(see docs/CONVENTIONS.md §1.2)",
            file=sys.stderr,
        )
        return 1

    app_path = base_dir / APPS_SUBPATH / app_name
    template_path = base_dir / TEMPLATE_SUBPATH

    if app_path.exists():
        print(
            f"❌ App '{app_name}' already exists at {APPS_SUBPATH}/{app_name}",
            file=sys.stderr,
        )
        return 1

    if not template_path.is_dir():
        print(f"❌ Template not found at {TEMPLATE_SUBPATH}", file=sys.stderr)
        return 1

    runner = copier_runner if copier_runner is not None else _resolve_copier()
    if runner is None:
        print(
            "❌ `copier` not found. Run `mise install` (it's in .mise.toml).",
            file=sys.stderr,
        )
        return 2

    today = dt.date.today().isoformat()
    cmd = list(runner) + [
        "copy",
        "--data",
        f"app_name={app_name}",
        "--data",
        f"today={today}",
        "--vcs-ref=HEAD",
        str(template_path),
        str(app_path),
    ]

    result = subprocess.run(cmd, cwd=base_dir)
    if result.returncode != 0:
        print(
            f"❌ copier failed (exit {result.returncode}).",
            file=sys.stderr,
        )
        return result.returncode

    register_in_root_kustomization(base_dir, app_name)
    _print_next_steps(app_name)
    return 0


def _print_next_steps(app_name):
    print()
    print("✅ App created successfully!")
    print()
    print("📋 Next steps:")
    print()
    print(f"1. Review manifests: vim k8s/apps/{app_name}/")
    print(f"2. Tune resource limits in k8s/apps/{app_name}/deployment.yaml")
    print(
        f"3. Validate manifests: kubectl kustomize k8s/apps/{app_name}/ "
        "| kubeconform -strict"
    )
    print(f"4. Write the service doc: vim docs/services/{app_name}.md")
    print("5. Regenerate the catalog: make generate-catalog")
    print(f"6. Commit & push — ArgoCD will sync `{app_name}` automatically.")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scaffold a new Kubernetes app from the Copier template.",
    )
    parser.add_argument(
        "app_name",
        nargs="?",
        help="App name (kebab-case)",
    )
    args = parser.parse_args(argv)

    if args.app_name is None:
        print("Usage: create_homelab_app.py <app-name>", file=sys.stderr)
        return 1

    return create_app(args.app_name, base_dir=Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
