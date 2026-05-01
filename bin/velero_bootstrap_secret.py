#!/usr/bin/env python3
"""Velero AWS credentials bootstrap — extract Terraform outputs into the SOPS Secret.

Reads `velero_aws_access_key_id` and `velero_aws_secret_access_key` from
`terraform output -raw`, formats them as an AWS shared-credentials INI
string, and re-encrypts `k8s/apps/velero/secret.yaml` in place.

Idempotent — running twice is safe and always reflects the current Terraform
state. Use after `terraform apply` (or whenever the IAM access key rotates).

Security:
  - Plaintext only ever touches a tempfile in /tmp with mode 0o600
  - Tempfile is unlinked in a try/finally even on error
  - Secret values are never printed; only status lines ("✓ Decrypted", ...)
  - Subprocess args always passed as a list (no shell=True)

Usage:
  python3 bin/velero_bootstrap_secret.py
  python3 bin/velero_bootstrap_secret.py --tf-dir infra/aws --secret k8s/apps/velero/secret.yaml
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TF_DIR = Path("infra/aws")
DEFAULT_SECRET_PATH = Path("k8s/apps/velero/secret.yaml")
ACCESS_KEY_OUTPUT = "velero_aws_access_key_id"
SECRET_KEY_OUTPUT = "velero_aws_secret_access_key"


# ── pure helpers (unit-testable) ────────────────────────────────────────────


def build_aws_credentials_ini(access_key: str, secret_key: str) -> str:
    """Return a multi-line AWS shared-credentials file for a single profile."""
    return (
        "[default]\n"
        f"aws_access_key_id = {access_key}\n"
        f"aws_secret_access_key = {secret_key}\n"
    )


def replace_cloud_value(plaintext_yaml: str, new_cloud: str) -> str:
    """Replace the multi-line `cloud:` value in stringData, preserving the rest.

    The Velero Secret has the shape:
        stringData:
          cloud: |
            [default]
            aws_access_key_id = ...
            aws_secret_access_key = ...

    We rewrite that block. Other keys in stringData (none today, but possible
    later) and the surrounding metadata/annotations are preserved.
    """
    lines = plaintext_yaml.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if not replaced and stripped.startswith("cloud:") and ("|" in stripped):
            indent = line[: len(line) - len(stripped)]
            value_indent = indent + "  "
            out.append(f"{indent}cloud: |\n")
            for cloud_line in new_cloud.splitlines():
                out.append(f"{value_indent}{cloud_line}\n")
            i += 1
            # Skip the existing block: any subsequent lines indented deeper
            # than the `cloud:` key belong to the old block.
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    i += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent <= len(indent):
                    break
                i += 1
            replaced = True
            continue
        out.append(line)
        i += 1
    if not replaced:
        raise ValueError(
            "could not find `cloud: |` block in stringData — "
            "is the secret manifest still in the expected shape?"
        )
    return "".join(out)


# ── subprocess wrappers (mockable in tests) ─────────────────────────────────


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


def decrypt_secret(secret_path: Path) -> str:
    """Return the plaintext YAML from a SOPS-encrypted file."""
    proc = subprocess.run(
        ["sops", "--decrypt", str(secret_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def encrypt_secret_in_place(secret_path: Path, plaintext: str) -> None:
    """Write `plaintext` to a tempfile, sops-encrypt it in place, then atomically swap.

    Uses NamedTemporaryFile with mode 0o600. Cleans up the tempfile in a
    try/finally regardless of outcome.
    """
    fd, tmp_path = tempfile.mkstemp(prefix="velero-secret-", suffix=".yaml", dir="/tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(plaintext)
        subprocess.run(
            ["sops", "--encrypt", "--in-place", tmp_path],
            check=True,
            capture_output=True,
            text=True,
        )
        # Atomic replace
        os.replace(tmp_path, secret_path)
        tmp_path = None  # signal no cleanup needed
    finally:
        if tmp_path is not None and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


# ── orchestration ───────────────────────────────────────────────────────────


def bootstrap(tf_dir: Path, secret_path: Path) -> None:
    """End-to-end: read TF outputs → decrypt → patch → re-encrypt."""
    print(f"📥 Reading terraform outputs from {tf_dir}...")
    access_key = get_terraform_output(ACCESS_KEY_OUTPUT, tf_dir)
    secret_key = get_terraform_output(SECRET_KEY_OUTPUT, tf_dir)
    print(f"  ✓ Got {ACCESS_KEY_OUTPUT} and {SECRET_KEY_OUTPUT}")

    print(f"🔓 Decrypting {secret_path}...")
    plaintext = decrypt_secret(secret_path)
    print("  ✓ Decrypted")

    print("✏️  Patching cloud credentials...")
    new_cloud = build_aws_credentials_ini(access_key, secret_key)
    patched = replace_cloud_value(plaintext, new_cloud)
    print("  ✓ Patched")

    print(f"🔐 Re-encrypting {secret_path} in place...")
    encrypt_secret_in_place(secret_path, patched)
    print("  ✓ Re-encrypted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf-dir", type=Path, default=DEFAULT_TF_DIR)
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = parser.parse_args(argv)

    try:
        bootstrap(args.tf_dir, args.secret)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Bootstrap failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
