#!/usr/bin/env python3
"""Pi-only Homelab — Deployment Orchestrator (no AWS, no Terraform).

Companion to bin/deploy_aws_homelab.py. Skips Terraform / EC2 / SSM and
deploys the k3s cluster + ArgoCD on the Raspberry Pis alone, using
inventory/production.yml + inventory/pi-only.yml as a layered overlay.

Phases:
  1. prerequisites  — SOPS canary, ansible/kubectl present, Pi inventory loads
  2. ansible        — `ansible-playbook -i production.yml -i pi-only.yml site.yml`
  3. verify         — ssh-slurp kubeconfig from rasp-pi-04, rewrite to Tailscale IP

Why not extend deploy_aws_homelab.py with a flag: the AWS script's six
phases (terraform / instances / ssm / tailscale / ansible / verify) are
tightly coupled. A separate ~150-line script keeps each path readable and
the .deploy-state.json resume contract intact for each mode.

Usage:
  python3 bin/deploy_pi_homelab.py
  python3 bin/deploy_pi_homelab.py --resume-from=ansible
  python3 bin/deploy_pi_homelab.py --reset-state
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Isolate the Pi state file from the AWS state file. Both scripts share the
# same state-machine helpers (imported below), and the AWS default is
# .deploy-state.json — using the same file would let a Pi-only "ansible" run
# satisfy a hybrid `--resume-from=verify` within the 2-hour freshness window.
os.environ.setdefault("HOMELAB_DEPLOY_STATE_FILE", ".deploy-state-pi.json")

# Reuse the AWS script's shared utilities (logging, state machine, SOPS
# canary check, kubeconfig rewrite). Keeping these single-sourced avoids the
# usual problem of two deploy paths drifting in their error messages and
# resume semantics.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_aws_homelab import (  # noqa: E402  (sys.path mutation before import)
    BLUE,
    GREEN,
    NC,
    clear_state,
    error_exit,
    find_sops_secret_files,
    is_stage_fresh,
    load_state,
    log_info,
    log_success,
    log_warning,
    mark_stage_completed,
    rewrite_kubeconfig,
    should_skip_stage,
    state_file_path,
)

DEFAULT_ANSIBLE_DIR = "ansible"
PRODUCTION_INVENTORY = "inventory/production.yml"
PI_ONLY_INVENTORY = "inventory/pi-only.yml"
KUBECONFIG_DEST = "/tmp/k3s-homelab-kubeconfig.yaml"
KUBECONFIG_REMOTE = "/etc/rancher/k3s/k3s.yaml"
SERVER_HOST = "rasp-pi-04"
SERVER_TAILSCALE_IP = "100.84.176.35"
STAGES = ("prerequisites", "ansible", "verify")


def check_prerequisites(ansible_dir):
    """SOPS canary + tool presence + inventory files exist."""
    log_info("Checking prerequisites...")

    for tool in ("ansible-playbook", "sops", "ssh"):
        if shutil.which(tool) is None:
            error_exit(f"{tool} not found in PATH.")

    if not Path(ansible_dir).is_dir():
        error_exit(f"Ansible directory not found: {ansible_dir}")

    for relpath in (PRODUCTION_INVENTORY, PI_ONLY_INVENTORY):
        path = Path(ansible_dir) / relpath
        if not path.is_file():
            error_exit(f"Inventory file missing: {path}")

    secret_files = find_sops_secret_files()
    if not secret_files:
        error_exit("No k8s/**/secret.yaml files found — repo layout unexpected.")

    failures = []
    for secret_file in secret_files:
        try:
            subprocess.run(
                ["sops", "--decrypt", str(secret_file)],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
            first_line = stderr.splitlines()[0] if stderr else "(no stderr)"
            failures.append((secret_file, first_line))

    if failures:
        for path, err in failures:
            log_warning(f"SOPS decrypt failed: {path}: {err}")
        error_exit(f"SOPS decryption failed on {len(failures)} files.")

    log_success(f"SOPS verified ({len(secret_files)} files), tools present")


def phase_ansible(ansible_dir):
    """Run site.yml against the layered Pi-only inventory."""
    print()
    log_info("==========================================")
    log_info("Phase: Kubernetes Cluster (Ansible) — Pi-only")
    log_info("==========================================")
    print()
    log_info(f"Inventories: {PRODUCTION_INVENTORY} + {PI_ONLY_INVENTORY}")
    log_info("Estimated time: 20-30 min on first run")
    print()
    rc = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            PRODUCTION_INVENTORY,
            "-i",
            PI_ONLY_INVENTORY,
            "playbooks/site.yml",
        ],
        cwd=ansible_dir,
    ).returncode
    if rc != 0:
        error_exit("Ansible playbook failed (Pi-only path)")
    log_success("Ansible deploy complete")


def phase_verify(ansible_dir):
    """Pull /etc/rancher/k3s/k3s.yaml from rasp-pi-04 via ansible-slurp and rewrite."""
    print()
    log_info("==========================================")
    log_info("Phase: Verify & Export Kubeconfig")
    log_info("==========================================")
    print()
    log_info(f"Slurping {KUBECONFIG_REMOTE} from {SERVER_HOST} via SSH...")

    result = subprocess.run(
        [
            "ansible",
            SERVER_HOST,
            "-i",
            PRODUCTION_INVENTORY,
            "-i",
            PI_ONLY_INVENTORY,
            "-m",
            "ansible.builtin.slurp",
            "-a",
            f"src={KUBECONFIG_REMOTE}",
            "--become",
            "-o",
        ],
        cwd=ansible_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_warning(result.stderr.strip() or result.stdout.strip())
        error_exit(
            f"Could not retrieve kubeconfig from {SERVER_HOST}. "
            "Is the k3s server up?"
        )

    # ansible -o emits "host | SUCCESS => {json}". Find the JSON payload and
    # decode the 'content' field (base64-encoded kubeconfig).
    import base64
    import json
    import re

    match = re.search(r"=>\s*(\{.*\})", result.stdout, re.DOTALL)
    if not match:
        error_exit(
            "Unexpected slurp output — could not find JSON payload. "
            f"Raw: {result.stdout[:200]}"
        )
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        error_exit(f"Slurp JSON parse error: {exc}")

    encoded = payload.get("content")
    if not encoded:
        error_exit("Slurp payload missing 'content' — kubeconfig empty on server.")
    content = base64.b64decode(encoded).decode("utf-8")

    rewrite_kubeconfig(content, SERVER_TAILSCALE_IP, KUBECONFIG_DEST)
    log_success(f"Kubeconfig saved to {KUBECONFIG_DEST}")
    log_info(f"  export KUBECONFIG={KUBECONFIG_DEST}")
    log_info("  kubectl get nodes")


def print_banner():
    print(BLUE, end="")
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║                  PI-ONLY HOMELAB DEPLOYMENT                    ║")
    print("║                                                                ║")
    print("║  Ansible → k3s on rasp-pi-04 + agent on rasp-pi-03 → ArgoCD   ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print(NC)


def print_summary():
    print()
    print(
        f"{GREEN}╔════════════════════════════════════════════════════════════════╗{NC}"
    )
    print(
        f"{GREEN}║         PI-ONLY DEPLOYMENT COMPLETED SUCCESSFULLY!             ║{NC}"
    )
    print(
        f"{GREEN}╚════════════════════════════════════════════════════════════════╝{NC}"
    )
    print()
    print(f"{BLUE}Access:{NC}")
    print(f"  export KUBECONFIG={KUBECONFIG_DEST}")
    print("  kubectl get nodes")
    print()
    print(f"{BLUE}ArgoCD UI:{NC}")
    print("  kubectl port-forward svc/argocd-server -n argocd 8080:443")
    print("  URL: https://localhost:8080  |  Username: admin")
    print()
    print(f"{BLUE}Rollback to hybrid AWS+Pi:{NC}")
    print("  See docs/operations/pi-only-deploy.md")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Pi-only homelab deployment orchestrator (no AWS).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--resume-from",
        choices=STAGES,
        help="Skip prior stages that completed within 2 hours.",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Delete .deploy-state.json and exit. No deploy is run.",
    )
    args = parser.parse_args(argv)

    if args.reset_state:
        clear_state()
        log_success(f"Deploy state cleared: {state_file_path()}")
        return 0

    print_banner()

    ansible_dir = DEFAULT_ANSIBLE_DIR
    state = load_state()
    stages_plan = (
        ("prerequisites", lambda: check_prerequisites(ansible_dir)),
        ("ansible", lambda: phase_ansible(ansible_dir)),
        ("verify", lambda: phase_verify(ansible_dir)),
    )

    if args.resume_from:
        log_info(f"▶ Resuming from stage: {args.resume_from}")

    for stage_name, runner in stages_plan:
        if should_skip_stage(stage_name, args.resume_from, state):
            log_info(f"⏩ Skipping {stage_name} (fresh state, resume target ahead)")
            continue
        if args.resume_from and STAGES.index(stage_name) < STAGES.index(
            args.resume_from
        ):
            if not is_stage_fresh(state, stage_name):
                log_warning(
                    f"⚠️  {stage_name} not in fresh state — re-running before resume target"
                )
        runner()
        mark_stage_completed(stage_name)

    print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
