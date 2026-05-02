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
from datetime import datetime, timezone
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


def parse_quota_response(stdout):
    """Return the integer Quota.Value from `aws service-quotas get-service-quota`.

    Returns 0 on blank/malformed input — caller treats 0 as "couldn't read".
    """
    if not (stdout or "").strip():
        return 0
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return 0
    value = data.get("Quota", {}).get("Value")
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_tailscale_key_expiry(stdout):
    """Return seconds-until-expiry of the local Tailscale key.

    -1 sentinel for "no key" or "never expires" — caller skips the check.
    """
    if not (stdout or "").strip():
        return -1
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return -1
    expiry = (data.get("Self") or {}).get("KeyExpiry")
    if not expiry or str(expiry).startswith("0001-"):
        return -1
    try:
        ts = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return -1
    return int((ts - datetime.now(timezone.utc)).total_seconds())


_CNI_NAME_PATTERNS = ("flannel", "cilium", "calico", "canal", "weave")


def parse_cni_daemonset_status(stdout):
    """Inspect `kubectl -n kube-system get daemonsets -o json`.

    Returns:
      None   — no CNI DaemonSet matched (caller skips the check)
      []     — all matched DSes have desired==ready (caller passes)
      [{...}] — list of diverged DSes (caller fails)
    """
    if not (stdout or "").strip():
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    matched_any = False
    diverged = []
    for item in data.get("items", []) or []:
        name = (item.get("metadata") or {}).get("name", "")
        if not any(p in name.lower() for p in _CNI_NAME_PATTERNS):
            continue
        matched_any = True
        status = item.get("status") or {}
        desired = int(status.get("desiredNumberScheduled", 0) or 0)
        ready = int(status.get("numberReady", 0) or 0)
        if ready != desired:
            diverged.append({"name": name, "desired": desired, "ready": ready})
    if not matched_any:
        return None
    return diverged


def parse_velero_backup_freshness(stdout):
    """Return age (in seconds) of newest Completed Velero backup.

    None if no Completed backups exist — caller surfaces a 'no backups' warn.
    """
    if not (stdout or "").strip():
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    newest_ts = None
    for item in data.get("items", []) or []:
        status = item.get("status") or {}
        if status.get("phase") != "Completed":
            continue
        ts_str = status.get("completionTimestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if newest_ts is None or ts > newest_ts:
            newest_ts = ts
    if newest_ts is None:
        return None
    return (datetime.now(timezone.utc) - newest_ts).total_seconds()


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

    def check_aws_quota(self):
        """Verify EC2 RunInstances quota has headroom for the planned deploy.

        Standard On-Demand quota code: L-1216C47A. Compare against the
        configured `--planned-instances` (CLI flag, default 4 for the
        homelab footprint of server + agents).

        - quota >= 4× planned → pass (4× headroom is the comfort margin)
        - planned <= quota < 4× planned → warn (proceed but flag risk)
        - quota < planned → fail (deploy will hit RunInstances throttle)
        """
        if self.args.skip_aws:
            self.skip("aws.quota", "--skip-aws")
            return
        if not shutil.which("aws"):
            self.fail("aws.quota", "aws CLI missing")
            return
        try:
            result = self.run(
                [
                    "aws",
                    "service-quotas",
                    "get-service-quota",
                    "--service-code",
                    "ec2",
                    "--quota-code",
                    "L-1216C47A",
                    "--output",
                    "json",
                ]
            )
        except subprocess.TimeoutExpired:
            self.warn("aws.quota", "timed out")
            return
        if result.returncode != 0:
            self.warn(
                "aws.quota",
                (result.stderr or "get-service-quota failed").strip().splitlines()[0],
            )
            return
        quota = parse_quota_response(result.stdout)
        planned = int(getattr(self.args, "planned_instances", 4) or 4)
        if quota == 0:
            self.warn("aws.quota", "couldn't read RunInstances quota")
            return
        if quota < planned:
            self.fail(
                "aws.quota",
                f"RunInstances quota {quota} < planned {planned} — deploy will throttle",
            )
            return
        if quota < planned * 4:
            self.warn(
                "aws.quota",
                f"RunInstances quota {quota} (planned {planned}, want >= {planned * 4})",
            )
            return
        self.pass_("aws.quota", f"RunInstances quota {quota} (planned {planned})")

    def check_tailscale_key_expiry(self):
        """Warn if the local Tailscale node-key expires within 24h."""
        if not shutil.which("tailscale"):
            self.skip("tailscale.key_expiry", "tailscale CLI missing")
            return
        try:
            result = self.run(["tailscale", "status", "--json"])
        except subprocess.TimeoutExpired:
            self.warn("tailscale.key_expiry", "timed out")
            return
        if result.returncode != 0:
            self.warn("tailscale.key_expiry", "status query failed")
            return
        secs = parse_tailscale_key_expiry(result.stdout)
        if secs < 0:
            self.skip("tailscale.key_expiry", "no expiring key on this node")
            return
        hours = secs // 3600
        if secs <= 0:
            self.fail("tailscale.key_expiry", "key already expired")
            return
        if hours < 24:
            self.warn(
                "tailscale.key_expiry",
                f"expires in {hours}h — re-auth before deploy",
            )
            return
        self.pass_("tailscale.key_expiry", f"expires in {hours // 24}d {hours % 24}h")

    def check_cni_ready(self):
        """Guard against the CNI race: refuse deploy if flannel/cilium pods aren't all Ready.

        Pods with `hostNetwork: false` flap if applied before the CNI
        DaemonSet has converged. This check enforces `desiredNumberScheduled
        == numberReady` on every recognised CNI DS in `kube-system`.
        """
        if not shutil.which("kubectl"):
            self.skip("cluster.cni_ready", "kubectl missing")
            return
        try:
            result = self.run(
                [
                    "kubectl",
                    "-n",
                    "kube-system",
                    "get",
                    "daemonsets",
                    "-o",
                    "json",
                ]
            )
        except subprocess.TimeoutExpired:
            self.warn("cluster.cni_ready", "timed out")
            return
        if result.returncode != 0:
            self.warn(
                "cluster.cni_ready",
                (result.stderr or "list failed").strip().splitlines()[0],
            )
            return
        diverged = parse_cni_daemonset_status(result.stdout)
        if diverged is None:
            self.skip("cluster.cni_ready", "no recognised CNI DaemonSet")
            return
        if diverged:
            details = ", ".join(
                f"{d['name']} {d['ready']}/{d['desired']}" for d in diverged
            )
            self.fail("cluster.cni_ready", f"CNI not converged: {details}")
            return
        self.pass_("cluster.cni_ready", "all CNI DaemonSets fully scheduled")

    def check_velero_backup_fresh(self):
        """Warn if the newest Completed Velero backup is > 24h old.

        Going to deploy with a stale backup means the recovery window is
        wider than the SLA — surface it before the change, not after.
        """
        if not shutil.which("kubectl"):
            self.skip("velero.backup_fresh", "kubectl missing")
            return
        try:
            result = self.run(
                ["kubectl", "-n", "velero", "get", "backups", "-o", "json"]
            )
        except subprocess.TimeoutExpired:
            self.warn("velero.backup_fresh", "timed out")
            return
        if result.returncode != 0:
            self.warn(
                "velero.backup_fresh",
                (result.stderr or "list failed").strip().splitlines()[0],
            )
            return
        age = parse_velero_backup_freshness(result.stdout)
        if age is None:
            self.warn("velero.backup_fresh", "no Completed Velero backups visible")
            return
        hours = int(age // 3600)
        if hours > 24:
            self.warn(
                "velero.backup_fresh",
                f"newest backup is {hours}h ago (> 24h SLA — likely stale)",
            )
            return
        self.pass_("velero.backup_fresh", f"newest backup {hours}h ago")

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
        self.check_aws_quota()
        self.check_sops_decrypt()
        self.check_tailscale()
        self.check_tailscale_key_expiry()
        self.check_ssh()
        self.check_aws_ssm()
        self.check_kubeconfig()
        self.check_cni_ready()
        self.check_velero_backup_fresh()
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
    p.add_argument(
        "--planned-instances",
        type=int,
        default=4,
        help="EC2 instance count for the upcoming deploy (used by AWS quota check; default: 4)",
    )
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    pf = Preflight(args)
    pf.run_all()
    pf.render(sys.stdout)
    return pf.exit_code()


if __name__ == "__main__":
    sys.exit(main())
