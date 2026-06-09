#!/usr/bin/env python3
"""SSM activation bootstrap — extract Terraform outputs into the SOPS group_vars.

Reads `ssm_activation_id` and `ssm_activation_code` from
`terraform -chdir=infra/aws-velero output -raw` and writes them into the
SOPS-encrypted `ansible/group_vars/all.sops.yml` via `sops set` (which decrypts,
updates the key, and re-encrypts in place — requires the age private key).

Idempotent — re-run after `terraform apply -replace=aws_ssm_activation.pi` mints
a fresh activation. Values are never printed.

Usage:
  python3 bin/ssm_activation_bootstrap.py
  python3 bin/ssm_activation_bootstrap.py --tf-dir infra/aws-velero \
      --vars ansible/group_vars/all.sops.yml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_TF_DIR = Path("infra/aws-velero")
DEFAULT_VARS_PATH = Path("ansible/group_vars/all.sops.yml")
# TF output name -> group_vars key.
OUTPUT_TO_KEY = {
    "ssm_activation_id": "ssm_activation_id",
    "ssm_activation_code": "ssm_activation_code",
}


def get_terraform_output(name: str, tf_dir: Path) -> str:
    """Return the value of `terraform output -raw <name>`; raise on empty/missing."""
    proc = subprocess.run(
        ["terraform", f"-chdir={tf_dir}", "output", "-raw", name],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"terraform output -raw {name} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    value = proc.stdout.strip()
    if not value:
        raise RuntimeError(
            f"terraform output -raw {name} is empty — did you run `terraform apply`?"
        )
    return value


def sops_set(vars_path: Path, key: str, value: str) -> None:
    """Set a top-level key in a SOPS file (decrypt → update → re-encrypt in place)."""
    subprocess.run(
        ["sops", "set", str(vars_path), f'["{key}"]', json.dumps(value)],
        check=True,
        capture_output=True,
        text=True,
    )


def bootstrap(tf_dir: Path, vars_path: Path) -> None:
    """End-to-end: read TF outputs → sops set each key."""
    print(f"📥 Reading SSM activation outputs from {tf_dir}...")
    for output_name, key in OUTPUT_TO_KEY.items():
        value = get_terraform_output(output_name, tf_dir)
        sops_set(vars_path, key, value)
        print(f"  ✓ Set {key} in {vars_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf-dir", type=Path, default=DEFAULT_TF_DIR)
    parser.add_argument("--vars", type=Path, default=DEFAULT_VARS_PATH)
    args = parser.parse_args(argv)

    try:
        bootstrap(args.tf_dir, args.vars)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Bootstrap failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
