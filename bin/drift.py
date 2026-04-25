#!/usr/bin/env python3
"""Drift detection for the homelab stack — Terraform / ArgoCD / inventory.

Runs three independent probes and returns a non-zero exit code if any drift
is detected.  When drift is found the script offers to auto-fix it.

Usage:
  python3 bin/drift.py [--skip-tf] [--skip-argo] [--skip-inventory]
                       [-o text|json] [--kubeconfig PATH]
                       [--fix] [--no-fix]

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
        # Populated during checks; used by fix methods.
        self._tf_drifted = False
        self._argo_drifted_apps: list[str] = []

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
            self._tf_drifted = True
            n = _count_tf_changed_resources(plan.stdout)
            detail = f"{n} resource(s) changed" if n else "changes detected"
            self.fail("tf.drift", f"drift detected — {detail} (run: terraform apply -refresh-only)")
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
            a for a in apps
            if a.sync_status != "Synced" or a.health_status != "Healthy"
        ]
        if bad:
            self._argo_drifted_apps = [a.name for a in bad]
            labels = [
                f"{a.name}(sync={a.sync_status},health={a.health_status})"
                for a in bad
            ]
            self.fail(
                "argo.drift",
                f"{len(bad)}/{len(apps)} not Synced+Healthy: {', '.join(labels[:5])}",
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

    # ── auto-fix ─────────────────────────────────────────────────────────────

    def fix_terraform(self, stream) -> bool:
        """Apply a refresh-only plan to reconcile Terraform state with AWS reality."""
        stream.write("  → running: terraform apply -refresh-only -auto-approve\n")
        try:
            result = subprocess.run(
                [
                    "terraform",
                    f"-chdir={TERRAFORM_DIR}",
                    "apply",
                    "-refresh-only",
                    "-auto-approve",
                    "-input=false",
                ],
                timeout=self.timeout * 4,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            stream.write(f"  ✗ terraform apply failed: {e}\n")
            return False
        if result.returncode == 0:
            stream.write("  ✓ Terraform state refreshed\n")
            return True
        stream.write(f"  ✗ terraform apply exited {result.returncode}\n")
        return False

    def fix_argo(self, stream) -> bool:
        """Sync each out-of-sync ArgoCD application."""
        if not self._argo_drifted_apps:
            return True
        # Prefer argocd CLI; fall back to kubectl annotation trigger.
        use_argocd = _which("argocd") is not None
        all_ok = True
        env = os.environ.copy()
        env["KUBECONFIG"] = self.kubeconfig
        for app in self._argo_drifted_apps:
            if use_argocd:
                cmd = ["argocd", "app", "sync", app, "--prune"]
            else:
                # Trigger a hard refresh via annotation; ArgoCD picks it up.
                cmd = [
                    "kubectl", "annotate", "application", app,
                    "-n", "argocd",
                    "argocd.argoproj.io/refresh=hard",
                    "--overwrite",
                ]
            stream.write(f"  → {' '.join(cmd)}\n")
            try:
                r = subprocess.run(cmd, env=env, timeout=self.timeout * 2)
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                stream.write(f"  ✗ {app}: {e}\n")
                all_ok = False
                continue
            if r.returncode == 0:
                stream.write(f"  ✓ {app} synced\n")
            else:
                stream.write(f"  ✗ {app}: exit {r.returncode}\n")
                all_ok = False
        if not use_argocd:
            stream.write(
                "  ℹ  argocd CLI not found — used kubectl annotation refresh.\n"
                "     For a hard sync install argocd CLI and run: argocd app sync <name>\n"
            )
        return all_ok

    def offer_fixes(self, stream) -> int:
        """Print fix summary and, if appropriate, perform fixes.

        Returns an updated exit code: 0 if all fixes succeeded, 1 otherwise.
        """
        fixable = self._tf_drifted or bool(self._argo_drifted_apps)
        if not fixable:
            return self.exit_code()

        no_fix = getattr(self.args, "no_fix", False)
        do_fix = getattr(self.args, "fix", False)

        if no_fix:
            return self.exit_code()

        if not do_fix:
            # Prompt only when connected to a real terminal.
            if not sys.stdin.isatty():
                stream.write(
                    "\nAuto-fix available. Re-run with --fix to apply, or --no-fix to silence this.\n"
                )
                return self.exit_code()
            stream.write("\nDrift detected. Auto-fix options:\n")
            if self._tf_drifted:
                stream.write("  [TF]   terraform apply -refresh-only -auto-approve\n")
            for app in self._argo_drifted_apps:
                stream.write(f"  [Argo] argocd app sync {app}\n")
            try:
                answer = input("\nApply fixes now? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                stream.write("\n")
                return self.exit_code()
            if answer not in ("y", "yes"):
                return self.exit_code()

        stream.write("\n▶ fixing\n")
        all_ok = True
        if self._tf_drifted:
            stream.write("\n[TF] Refreshing Terraform state\n")
            all_ok &= self.fix_terraform(stream)
        if self._argo_drifted_apps:
            stream.write("\n[Argo] Syncing ArgoCD apps\n")
            all_ok &= self.fix_argo(stream)

        if all_ok:
            stream.write("\n✓ All fixes applied. Re-run drift to verify.\n")
            return 0
        stream.write("\n✗ Some fixes failed — check output above.\n")
        return 1

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


# ── helpers ───────────────────────────────────────────────────────────────────


def _count_tf_changed_resources(plan_stdout: str) -> int:
    """Count resources reported as changed in a terraform plan -refresh-only output."""
    return sum(
        1
        for line in plan_stdout.splitlines()
        if line.strip().startswith("# ") and "has changed" in line
    )


def _which(cmd: str):
    """Return the path to cmd if it exists on PATH, else None."""
    import shutil
    return shutil.which(cmd)


# ── CLI ───────────────────────────────────────────────────────────────────────


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

    fix_group = p.add_mutually_exclusive_group()
    fix_group.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="auto-apply fixes without prompting (terraform refresh + argocd sync)",
    )
    fix_group.add_argument(
        "--no-fix",
        action="store_true",
        default=False,
        help="never prompt to fix (CI/monitoring mode)",
    )
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    d = Drift(args)
    d.run_all()
    d.render(sys.stdout)
    return d.offer_fixes(sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
