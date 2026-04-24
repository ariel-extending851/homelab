#!/usr/bin/env python3
"""Pre-deploy chain checks — fail fast on seam-level hazards before ``make deploy``.

Covers the blind spots that individual validators miss: SOPS decrypt canary,
Tailscale reachability, SSH reach to inventory hosts, SSM online, kubeconfig
sanity, AWS creds, and basic git hygiene.

Usage:
  python3 bin/preflight.py [--skip-aws] [--skip-ssh] [-o text|json]

Exit codes:
  0  all checks clean
  1  at least one fail (blocker)
  2  warnings only, no fails
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SOPS_CANARY = REPO_ROOT / "infra" / "aws" / "terraform.tfvars.sops.yaml"
ANSIBLE_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "production.yml"
REQUIRED_TOOLS = (
    "terraform",
    "ansible",
    "sops",
    "age",
    "kubectl",
    "tailscale",
    "python3",
)


# ── pure parsing helpers (contract-testable) ─────────────────────────────────


def parse_inventory_hosts(yaml_text):
    """Walk an Ansible inventory YAML string and return [(name, ansible_host)] pairs.

    Skips entries without ansible_host. Returns an empty list on parse errors.
    """
    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return []
    hosts = []

    def walk(node):
        if not isinstance(node, dict):
            return
        children = node.get("hosts")
        if isinstance(children, dict):
            for name, attrs in children.items():
                attrs = attrs or {}
                host = attrs.get("ansible_host") if isinstance(attrs, dict) else None
                if host:
                    hosts.append((name, host))
        for k, v in node.items():
            if k == "hosts":
                continue
            if isinstance(v, dict):
                walk(v)

    walk(doc)
    return hosts


def parse_tailscale_status(stdout):
    """Return (backend_state, online_peer_count) from `tailscale status --json`.

    Returns ('', 0) on blank / malformed input.
    """
    if not (stdout or "").strip():
        return "", 0
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "", 0
    state = data.get("BackendState", "")
    peers = data.get("Peer") or {}
    online = sum(1 for p in peers.values() if isinstance(p, dict) and p.get("Online"))
    return state, online


def parse_ssm_online(stdout):
    """Count instances with PingStatus=Online in AWS SSM JSON output."""
    if not (stdout or "").strip():
        return 0
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return 0
    items = data.get("InstanceInformationList") or []
    return sum(1 for i in items if i.get("PingStatus") == "Online")


def parse_sts_identity(stdout):
    """Return (account, arn) from `aws sts get-caller-identity` JSON."""
    if not (stdout or "").strip():
        return "", ""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "", ""
    return data.get("Account", ""), data.get("Arn", "")


# ── orchestrator ─────────────────────────────────────────────────────────────


class Preflight:
    def __init__(self, args):
        self.args = args
        self.checks = []
        self.timeout = args.timeout
        self.kubeconfig = (
            args.kubeconfig
            or os.environ.get("KUBECONFIG")
            or os.path.expanduser("~/.kube/config")
        )

    # ── recording ────────────────────────────────────────────────────────────

    def _add(self, name, status, message):
        self.checks.append({"name": name, "status": status, "message": message})

    def pass_(self, name, message=""):
        self._add(name, "pass", message)

    def warn(self, name, message=""):
        self._add(name, "warn", message)

    def fail(self, name, message=""):
        self._add(name, "fail", message)

    def skip(self, name, message=""):
        self._add(name, "skip", message)

    # ── helpers ──────────────────────────────────────────────────────────────

    def run(self, cmd):
        return subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)

    # ── checks ───────────────────────────────────────────────────────────────

    def check_tools(self):
        for tool in REQUIRED_TOOLS:
            if shutil.which(tool):
                self.pass_(f"tool.{tool}", "present")
            else:
                self.fail(f"tool.{tool}", "not on PATH")

    def check_aws_creds(self):
        if self.args.skip_aws:
            self.skip("aws.creds", "--skip-aws")
            return
        if not shutil.which("aws"):
            self.fail("aws.creds", "aws CLI missing")
            return
        try:
            result = self.run(["aws", "sts", "get-caller-identity", "--output", "json"])
        except subprocess.TimeoutExpired:
            self.fail("aws.creds", "timed out")
            return
        if result.returncode != 0:
            self.fail(
                "aws.creds",
                (result.stderr or "get-caller-identity failed").strip().splitlines()[0],
            )
            return
        account, arn = parse_sts_identity(result.stdout)
        self.pass_("aws.creds", f"account={account} arn={arn}")

    def check_sops_decrypt(self):
        if not SOPS_CANARY.exists():
            self.skip("sops.decrypt", f"canary missing: {SOPS_CANARY}")
            return
        if not shutil.which("sops"):
            self.fail("sops.decrypt", "sops CLI missing")
            return
        try:
            result = self.run(["sops", "-d", str(SOPS_CANARY)])
        except subprocess.TimeoutExpired:
            self.fail("sops.decrypt", "timed out")
            return
        if result.returncode != 0:
            self.fail(
                "sops.decrypt",
                "age key cannot decrypt canary — deploy will silently fall back to mock secrets",
            )
            return
        self.pass_("sops.decrypt", "age key decrypts canary")

    def check_tailscale(self):
        if not shutil.which("tailscale"):
            self.fail("tailscale.status", "tailscale CLI missing")
            return
        try:
            result = self.run(["tailscale", "status", "--json"])
        except subprocess.TimeoutExpired:
            self.fail("tailscale.status", "timed out")
            return
        if result.returncode != 0:
            self.fail(
                "tailscale.status",
                (result.stderr or "status failed").strip().splitlines()[0],
            )
            return
        state, online = parse_tailscale_status(result.stdout)
        if state != "Running":
            self.fail("tailscale.status", f"backend state {state or '(unknown)'}")
            return
        self.pass_("tailscale.status", f"Running; {online} peer(s) online")

    def check_ssh(self):
        if self.args.skip_ssh:
            self.skip("ssh.reach", "--skip-ssh")
            return
        if not ANSIBLE_INVENTORY.exists():
            self.skip("ssh.reach", f"inventory missing: {ANSIBLE_INVENTORY}")
            return
        hosts = parse_inventory_hosts(ANSIBLE_INVENTORY.read_text())
        if not hosts:
            self.skip("ssh.reach", "no static hosts in inventory")
            return

        def probe(host):
            try:
                with socket.create_connection((host, 22), timeout=3):
                    return True
            except (socket.gaierror, socket.timeout, OSError):
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda nh: probe(nh[1]), hosts))
        reachable = sum(results)
        if reachable == len(hosts):
            self.pass_("ssh.reach", f"{reachable}/{len(hosts)} hosts reachable on :22")
        else:
            self.warn("ssh.reach", f"{reachable}/{len(hosts)} hosts reachable on :22")

    def check_aws_ssm(self):
        if self.args.skip_aws:
            self.skip("aws.ssm", "--skip-aws")
            return
        if not shutil.which("aws"):
            self.fail("aws.ssm", "aws CLI missing")
            return
        try:
            result = self.run(
                ["aws", "ssm", "describe-instance-information", "--output", "json"]
            )
        except subprocess.TimeoutExpired:
            self.fail("aws.ssm", "timed out")
            return
        if result.returncode != 0:
            self.fail(
                "aws.ssm", (result.stderr or "describe failed").strip().splitlines()[0]
            )
            return
        online = parse_ssm_online(result.stdout)
        if online == 0:
            self.warn("aws.ssm", "no instances online via SSM")
        else:
            self.pass_("aws.ssm", f"{online} instance(s) online")

    def check_kubeconfig(self):
        path = self.kubeconfig
        if not path:
            self.warn("kube.config", "no kubeconfig path resolved")
            return
        if not os.path.exists(path):
            self.warn("kube.config", f"not found: {path}")
            return
        if os.path.getsize(path) == 0:
            self.fail("kube.config", f"empty file: {path}")
            return
        if not shutil.which("kubectl"):
            self.fail("kube.config", "kubectl missing")
            return
        env = os.environ.copy()
        env["KUBECONFIG"] = path
        try:
            result = subprocess.run(
                ["kubectl", "--request-timeout=5s", "version", "--output=json"],
                capture_output=True,
                text=True,
                env=env,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            self.warn("kube.config", "server unreachable (timed out)")
            return
        if result.returncode != 0:
            self.warn(
                "kube.config",
                f"server unreachable: {(result.stderr or '').strip().splitlines()[0] if result.stderr else 'no detail'}",
            )
            return
        self.pass_("kube.config", f"{path} reachable")

    def check_git(self):
        if not shutil.which("git"):
            self.skip("git.state", "git missing")
            return
        try:
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            self.skip("git.state", "timed out")
            return
        if result.returncode != 0:
            self.skip("git.state", "not a git repo")
            return
        if result.stdout.strip():
            self.warn("git.state", "uncommitted changes present")
        else:
            self.pass_("git.state", "clean worktree")

    # ── orchestrate ──────────────────────────────────────────────────────────

    def run_all(self):
        self.check_tools()
        self.check_aws_creds()
        self.check_sops_decrypt()
        self.check_tailscale()
        self.check_ssh()
        self.check_aws_ssm()
        self.check_kubeconfig()
        self.check_git()

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
            json.dump({"command": "preflight", "checks": self.checks}, stream, indent=2)
            stream.write("\n")
            return
        markers = {"pass": "  ✓", "warn": "  ⚠", "fail": "  ✗", "skip": "  ⊘"}
        stream.write("▶ preflight\n")
        for check in self.checks:
            marker = markers.get(check["status"], "  ?")
            stream.write(f"{marker} {check['name']:<26} {check['message']}\n")
        c = self.counts()
        stream.write(
            f"\n{c['pass']} pass  {c['warn']} warn  {c['fail']} fail  {c['skip']} skip\n"
        )


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="Pre-deploy chain checks (homelab preflight)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--skip-aws", action="store_true", help="skip AWS/SSM probes")
    p.add_argument("--skip-ssh", action="store_true", help="skip SSH reachability")
    p.add_argument(
        "-o", "--output", choices=("text", "json"), default="text", help="output format"
    )
    p.add_argument("--kubeconfig", default=None, help="path to kubeconfig")
    p.add_argument("--timeout", type=int, default=30, help="per-command timeout (s)")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    pf = Preflight(args)
    pf.run_all()
    pf.render(sys.stdout)
    return pf.exit_code()


if __name__ == "__main__":
    sys.exit(main())
