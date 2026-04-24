#!/usr/bin/env python3
"""Drift detection for the homelab stack — Terraform / ArgoCD / inventory.

Runs three independent probes and returns a non-zero exit code if any drift
is detected.

Usage:
  python3 bin/drift.py [--skip-tf] [--skip-argo] [--skip-inventory]
                       [-o text|json] [--kubeconfig PATH]

Exit codes:
  0  no drift
  1  drift detected (or probe error)
  2  warnings only (e.g. inventory empty)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Reuse the ArgoCD-Application JSON parser from smoke_test (already contract-tested).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_test  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = REPO_ROOT / "infra" / "aws"
INVENTORY_SCRIPT = REPO_ROOT / "ansible" / "terraform_inventory_aws.py"


class Drift:
    def __init__(self, args):
        self.args = args
        self.checks = []
        self.timeout = args.timeout
        self.kubeconfig = (
            args.kubeconfig
            or os.environ.get("KUBECONFIG")
            or os.path.expanduser("~/.kube/config")
        )

    def _add(self, name, status, message):
        self.checks.append({"name": name, "status": status, "message": message})

    def pass_(self, name, msg=""):
        self._add(name, "pass", msg)

    def warn(self, name, msg=""):
        self._add(name, "warn", msg)

    def fail(self, name, msg=""):
        self._add(name, "fail", msg)

    def skip(self, name, msg=""):
        self._add(name, "skip", msg)

    # ── Terraform drift ──────────────────────────────────────────────────────

    def check_terraform(self):
        if self.args.skip_tf:
            self.skip("tf.drift", "--skip-tf")
            return
        if not TERRAFORM_DIR.exists():
            self.skip("tf.drift", f"no terraform dir at {TERRAFORM_DIR}")
            return
        try:
            init = subprocess.run(
                [
                    "terraform",
                    f"-chdir={TERRAFORM_DIR}",
                    "init",
                    "-input=false",
                    "-upgrade=false",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            self.fail("tf.drift", f"terraform init: {e}")
            return
        if init.returncode != 0:
            self.fail(
                "tf.drift",
                (init.stderr or "init failed").strip().splitlines()[0],
            )
            return
        try:
            plan = subprocess.run(
                [
                    "terraform",
                    f"-chdir={TERRAFORM_DIR}",
                    "plan",
                    "-refresh-only",
                    "-detailed-exitcode",
                    "-lock=false",
                    "-input=false",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout * 2,
            )
        except subprocess.TimeoutExpired:
            self.fail("tf.drift", "plan timed out")
            return
        # detailed-exitcode: 0 = no changes, 1 = error, 2 = drift
        if plan.returncode == 0:
            self.pass_("tf.drift", "no drift")
        elif plan.returncode == 2:
            self.fail(
                "tf.drift", "drift detected (plan -refresh-only reported changes)"
            )
        else:
            self.fail(
                "tf.drift",
                (plan.stderr or "plan failed").strip().splitlines()[0],
            )

    # ── ArgoCD drift ─────────────────────────────────────────────────────────

    def check_argo(self):
        if self.args.skip_argo:
            self.skip("argo.drift", "--skip-argo")
            return
        env = os.environ.copy()
        env["KUBECONFIG"] = self.kubeconfig
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "--request-timeout=10s",
                    "get",
                    "applications",
                    "-n",
                    "argocd",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=self.timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            self.fail("argo.drift", f"kubectl: {e}")
            return
        if result.returncode != 0:
            self.fail(
                "argo.drift",
                (result.stderr or "kubectl failed").strip().splitlines()[0],
            )
            return
        apps = smoke_test.parse_argocd_apps(result.stdout)
        if not apps:
            self.warn(
                "argo.drift", "no Application CRs found (cluster not bootstrapped?)"
            )
            return
        bad = [
            f"{a.name}(sync={a.sync_status},health={a.health_status})"
            for a in apps
            if a.sync_status != "Synced" or a.health_status != "Healthy"
        ]
        if bad:
            self.fail(
                "argo.drift",
                f"{len(bad)}/{len(apps)} not Synced+Healthy: {', '.join(bad[:5])}",
            )
        else:
            self.pass_("argo.drift", f"{len(apps)} apps all Synced+Healthy")

    # ── Inventory drift ──────────────────────────────────────────────────────

    def check_inventory(self):
        if self.args.skip_inventory:
            self.skip("inventory.drift", "--skip-inventory")
            return
        if not INVENTORY_SCRIPT.exists():
            self.skip("inventory.drift", f"script missing: {INVENTORY_SCRIPT}")
            return
        try:
            result = subprocess.run(
                ["python3", str(INVENTORY_SCRIPT), "--list"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            self.warn("inventory.drift", "timed out")
            return
        if result.returncode != 0:
            self.warn(
                "inventory.drift",
                (result.stderr or "inventory script failed").strip().splitlines()[0],
            )
            return
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            self.warn("inventory.drift", "inventory output is not valid JSON")
            return
        hostvars = (data.get("_meta") or {}).get("hostvars") or {}
        if not hostvars:
            self.warn(
                "inventory.drift", "inventory has zero hosts (terraform outputs empty?)"
            )
            return
        self.pass_("inventory.drift", f"{len(hostvars)} host(s) in dynamic inventory")

    # ── orchestrate ──────────────────────────────────────────────────────────

    def run_all(self):
        self.check_terraform()
        self.check_argo()
        self.check_inventory()

    def counts(self):
        c = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for check in self.checks:
            c[check["status"]] += 1
        return c

    def exit_code(self):
        c = self.counts()
        if c["fail"] > 0:
            return 1
        if c["warn"] > 0:
            return 2
        return 0

    def render(self, stream):
        if self.args.output == "json":
            json.dump({"command": "drift", "checks": self.checks}, stream, indent=2)
            stream.write("\n")
            return
        markers = {"pass": "  ✓", "warn": "  ⚠", "fail": "  ✗", "skip": "  ⊘"}
        stream.write("▶ drift\n")
        for check in self.checks:
            marker = markers.get(check["status"], "  ?")
            stream.write(f"{marker} {check['name']:<20} {check['message']}\n")
        c = self.counts()
        stream.write(
            f"\n{c['pass']} pass  {c['warn']} warn  {c['fail']} fail  {c['skip']} skip\n"
        )


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="Detect Terraform / ArgoCD / inventory drift",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--skip-tf", action="store_true", help="skip terraform plan probe")
    p.add_argument("--skip-argo", action="store_true", help="skip ArgoCD probe")
    p.add_argument("--skip-inventory", action="store_true", help="skip inventory probe")
    p.add_argument(
        "-o", "--output", choices=("text", "json"), default="text", help="output format"
    )
    p.add_argument("--kubeconfig", default=None, help="path to kubeconfig")
    p.add_argument("--timeout", type=int, default=60, help="per-command timeout (s)")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    d = Drift(args)
    d.run_all()
    d.render(sys.stdout)
    return d.exit_code()


if __name__ == "__main__":
    sys.exit(main())
