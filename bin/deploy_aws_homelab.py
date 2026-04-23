#!/usr/bin/env python3
"""AWS Homelab — Full Deployment Orchestrator.

Port of bin/deploy-aws-homelab.sh. Deploys the complete AWS
infrastructure (Terraform) + k3s cluster (Ansible) + ArgoCD + apps,
under a Zero Trust access model (Tailscale mesh + SSM).

Behavior preserved: identical exit codes, identical log prefixes
(INFO/SUCCESS/ERROR/WARNING), identical phase sequencing, identical
'yes' confirmation gate for --destroy, identical ACL-import check,
identical kubeconfig rewrite + 0600 perms, identical SSM polling and
Tailscale IP detection (100.x/8).

Usage:
  python3 bin/deploy_aws_homelab.py
  python3 bin/deploy_aws_homelab.py --destroy
  python3 bin/deploy_aws_homelab.py --help
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

DEFAULT_TERRAFORM_DIR = "infra/aws"
DEFAULT_ANSIBLE_DIR = "ansible"
DEFAULT_SSH_USER = "ec2-user"
DEFAULT_TIMEOUT = 600
KUBECONFIG_DEST = "/tmp/k3s-homelab-kubeconfig.yaml"
TAILSCALE_IP_RE = re.compile(r"^100\.")


# ── logging helpers ──────────────────────────────────────────────────────────


def log_info(msg):
    print(f"{BLUE}[INFO]{NC} {msg}")


def log_success(msg):
    print(f"{GREEN}[SUCCESS]{NC} {msg}")


def log_error(msg):
    print(f"{RED}[ERROR]{NC} {msg}")


def log_warning(msg):
    print(f"{YELLOW}[WARNING]{NC} {msg}")


def error_exit(msg):
    log_error(msg)
    sys.exit(1)


# ── configuration ────────────────────────────────────────────────────────────


class DeployConfig:
    def __init__(self, env=None):
        env = env if env is not None else os.environ
        self.terraform_dir = env.get("TERRAFORM_DIR", DEFAULT_TERRAFORM_DIR)
        self.ansible_dir = env.get("ANSIBLE_DIR", DEFAULT_ANSIBLE_DIR)
        self.ssh_user = env.get("SSH_USER", DEFAULT_SSH_USER)
        self.timeout = int(env.get("TIMEOUT", DEFAULT_TIMEOUT))
        self.sops_age_key = env.get("SOPS_AGE_KEY")
        self.sops_age_key_file = env.get("SOPS_AGE_KEY_FILE")
        self.aws_account_id = env.get("HOMELAB_AWS_ACCOUNT_ID")
        self.server_id = None
        self.agent_id = None


# ── parsing helpers (pure functions — contract-testable) ────────────────────


def parse_ssm_ping_status(stdout):
    """`aws ssm describe-instance-information --query ...PingStatus --output text`."""
    return (stdout or "").strip() or "None"


def parse_ssm_command_id(stdout):
    """`aws ssm send-command --query Command.CommandId --output text`."""
    return (stdout or "").strip()


def parse_ssm_invocation_status(stdout):
    """`aws ssm get-command-invocation --query Status --output text`.

    Returns Success/Failed/Pending/InProgress — or "Pending" if blank.
    """
    return (stdout or "").strip() or "Pending"


def parse_ssm_command_output(stdout):
    """StandardOutputContent — strip trailing newline only (preserve internal whitespace)."""
    return (stdout or "").rstrip("\n")


def extract_tailscale_ip(stdout):
    """Extract Tailscale IPv4 (100.x.x.x) from `tailscale ip -4`.

    Returns the IP if valid, empty string otherwise. Tolerates whitespace.
    """
    ip = re.sub(r"\s+", "", stdout or "")
    return ip if TAILSCALE_IP_RE.match(ip) else ""


def parse_terraform_state_has_acl(stdout):
    """True if tailscale_acl.homelab_acl appears in `terraform state list` output."""
    return "tailscale_acl.homelab_acl" in (stdout or "")


def parse_ec2_instance_id(stdout):
    """`aws ec2 describe-instances --query ...InstanceId --output text`."""
    return (stdout or "").strip()


def parse_ec2_instance_count(stdout):
    """`aws ec2 describe-instances --query length(...) --output text`. 0 on parse error."""
    try:
        return int((stdout or "0").strip())
    except ValueError:
        return 0


def parse_terraform_output_raw(stdout, returncode):
    """`terraform output -raw NAME` → stripped value on success, 'N/A' fallback."""
    if returncode == 0 and (stdout or "").strip():
        return stdout.strip()
    return "N/A"


# ── small utilities ──────────────────────────────────────────────────────────


def check_instance_count(count):
    if count > 2:
        log_error(
            f"Found {count} instances running (expected 2). "
            "Aborting to prevent orphans."
        )
        log_error(
            "Run: aws ec2 describe-instances "
            "--filters Name=instance-state-name,Values=running"
        )
        error_exit("Manual cleanup required before re-deploying.")
    log_success(f"Instance count verified: {count}/2")


def rewrite_kubeconfig(content, tailscale_ip, dest):
    """Replace 127.0.0.1 with tailscale_ip, write to dest with 0600 perms."""
    dest = Path(dest)
    rewritten = content.replace("127.0.0.1", tailscale_ip)
    dest.write_text(rewritten)
    dest.chmod(0o600)


# ── prerequisites ────────────────────────────────────────────────────────────


def check_sops_key(config):
    if shutil.which("sops") is None:
        error_exit("sops not found. Install: https://github.com/getsops/sops")

    key_configured = False
    if config.sops_age_key_file and Path(config.sops_age_key_file).is_file():
        key_configured = True
    if config.sops_age_key:
        key_configured = True

    if not key_configured:
        error_exit(
            "Age key not configured. " "Set SOPS_AGE_KEY_FILE or SOPS_AGE_KEY env var."
        )

    try:
        subprocess.run(
            ["sops", "--decrypt", "k8s/apps/adguard/secret.yaml"],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        error_exit(
            "SOPS decryption failed. Verify your Age key can decrypt "
            "k8s/apps/adguard/secret.yaml."
        )

    log_success("SOPS decryption verified")


def check_aws_account(config):
    """Refuse to deploy if the active AWS identity isn't the expected account.

    A stale AWS_PROFILE or leaked env var could otherwise apply to a wrong
    account. Set HOMELAB_AWS_ACCOUNT_ID in env to enable the check; absence
    is a soft warning, not a hard fail (preserves existing workflow).
    """
    expected = config.aws_account_id
    if not expected:
        log_warning(
            "HOMELAB_AWS_ACCOUNT_ID not set — skipping AWS account identity check"
        )
        return

    try:
        result = subprocess.run(
            [
                "aws",
                "sts",
                "get-caller-identity",
                "--query",
                "Account",
                "--output",
                "text",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        error_exit(f"aws sts get-caller-identity failed: {exc.stderr or exc}")

    actual = (result.stdout or "").strip()
    if actual != expected.strip():
        error_exit(
            f"Wrong AWS account: active={actual}, expected={expected}. "
            "Fix AWS_PROFILE / env vars before deploying."
        )
    log_success(f"AWS account verified: {actual}")


def check_prerequisites(config):
    log_info("Checking prerequisites...")

    if shutil.which("terraform") is None:
        error_exit("Terraform not found.")
    if shutil.which("ansible-playbook") is None:
        error_exit("Ansible not found. Install: pip3 install ansible")
    if shutil.which("aws") is None:
        error_exit("AWS CLI not found.")

    if not Path(config.terraform_dir).is_dir():
        error_exit(f"Terraform directory not found: {config.terraform_dir}")
    if not Path(config.ansible_dir).is_dir():
        error_exit(f"Ansible directory not found: {config.ansible_dir}")

    check_sops_key(config)
    check_aws_account(config)
    log_success("All prerequisites met")


# ── SSM helpers ──────────────────────────────────────────────────────────────


def wait_for_ssm(instance_id, config):
    """Poll SSM until the instance reports PingStatus=Online. Returns True/False."""
    max_attempts = config.timeout // 15
    log_info(f"Waiting for SSM agent on {instance_id}...")

    for _ in range(max_attempts):
        try:
            result = subprocess.run(
                [
                    "aws",
                    "ssm",
                    "describe-instance-information",
                    "--filters",
                    f"Key=InstanceIds,Values={instance_id}",
                    "--query",
                    "InstanceInformationList[0].PingStatus",
                    "--output",
                    "text",
                ],
                capture_output=True,
                text=True,
            )
            status = parse_ssm_ping_status(result.stdout)
        except Exception:
            status = "None"

        if status == "Online":
            log_success(f"SSM ready on {instance_id}")
            return True

        print(".", end="", flush=True)
        time.sleep(15)

    log_error(
        f"Timeout waiting for SSM on {instance_id} after {config.timeout} seconds"
    )
    return False


def ssm_run(instance_id, command):
    """Send a command via SSM and return its StandardOutputContent."""
    cmd_result = subprocess.run(
        [
            "aws",
            "ssm",
            "send-command",
            "--instance-ids",
            instance_id,
            "--document-name",
            "AWS-RunShellScript",
            "--parameters",
            f'commands=["{command}"]',
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    cmd_id = parse_ssm_command_id(cmd_result.stdout)

    for _ in range(15):
        time.sleep(3)
        try:
            status_result = subprocess.run(
                [
                    "aws",
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    cmd_id,
                    "--instance-id",
                    instance_id,
                    "--query",
                    "Status",
                    "--output",
                    "text",
                ],
                capture_output=True,
                text=True,
            )
            status = parse_ssm_invocation_status(status_result.stdout)
        except Exception:
            status = "Pending"

        if status in ("Success", "Failed"):
            break

    out_result = subprocess.run(
        [
            "aws",
            "ssm",
            "get-command-invocation",
            "--command-id",
            cmd_id,
            "--instance-id",
            instance_id,
            "--query",
            "StandardOutputContent",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    return parse_ssm_command_output(out_result.stdout)


def wait_for_tailscale_ip(instance_id, config):
    max_attempts = config.timeout // 10
    for _ in range(max_attempts):
        try:
            ts_ip = ssm_run(instance_id, "tailscale ip -4")
        except Exception:
            ts_ip = ""
        ts_ip = extract_tailscale_ip(ts_ip)
        if ts_ip:
            log_success(f"Tailscale IP found for {instance_id}: {ts_ip}")
            return True
        print(".", end="", flush=True)
        time.sleep(10)

    log_error(
        f"Timeout waiting for Tailscale IP on {instance_id} "
        f"after {config.timeout} seconds"
    )
    return False


# ── terraform / ansible drivers ──────────────────────────────────────────────


def _run_in_dir(args, cwd, error_message):
    """Run a command in cwd; error_exit with error_message on non-zero exit."""
    result = subprocess.run(args, cwd=cwd)
    if result.returncode != 0:
        error_exit(error_message)
    return result


# ── phases ───────────────────────────────────────────────────────────────────


def phase1_terraform(config):
    print()
    log_info("==========================================")
    log_info("Phase 1: AWS Infrastructure (Terraform)")
    log_info("==========================================")
    print()

    log_info("Initializing Terraform...")
    _run_in_dir(
        ["terraform", "init", "-upgrade"], config.terraform_dir, "Terraform init failed"
    )

    log_info("Validating Terraform configuration...")
    _run_in_dir(
        ["terraform", "validate"],
        config.terraform_dir,
        "Terraform validation failed",
    )

    log_info("Checking if Tailscale ACL needs to be imported...")
    state = subprocess.run(
        ["terraform", "state", "list"],
        cwd=config.terraform_dir,
        capture_output=True,
        text=True,
    )
    if parse_terraform_state_has_acl(state.stdout):
        log_success("Tailscale ACL is already managed by Terraform")
    else:
        log_warning("ACL not found in state. Attempting import...")
        import_rc = subprocess.run(
            ["terraform", "import", "tailscale_acl.homelab_acl", "acl"],
            cwd=config.terraform_dir,
        ).returncode
        if import_rc != 0:
            log_warning("Import failed (non-fatal).")

    log_info("Applying Terraform configuration...")
    _run_in_dir(
        ["terraform", "apply", "-auto-approve"],
        config.terraform_dir,
        "Terraform apply failed",
    )

    log_info("Refreshing state to capture live instance IPs...")
    refresh_rc = subprocess.run(
        ["terraform", "apply", "-refresh-only", "-auto-approve"],
        cwd=config.terraform_dir,
    ).returncode
    if refresh_rc != 0:
        log_warning("Refresh-only pass failed — outputs may show empty IPs (non-fatal)")

    log_success("AWS infrastructure created")


def _describe_instance_id(name_tag):
    result = subprocess.run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=tag:Name,Values={name_tag}",
            "Name=instance-state-name,Values=pending,running",
            "--query",
            "Reservations[0].Instances[0].InstanceId",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    return parse_ec2_instance_id(result.stdout)


def _count_running_instances():
    result = subprocess.run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--filters",
            "Name=tag:Name,Values=hl-k3s-server,hl-k3s-agent",
            "Name=instance-state-name,Values=pending,running",
            "--query",
            "length(Reservations[*].Instances[*])",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    return parse_ec2_instance_count(result.stdout)


def phase2_wait_for_instances(config):
    print()
    log_info("==========================================")
    log_info("Phase 2: Wait for EC2 Instances (SSM)")
    log_info("==========================================")
    print()

    log_info("Retrieving instance IDs from AWS...")
    server_id = _describe_instance_id("hl-k3s-server")
    agent_id = _describe_instance_id("hl-k3s-agent")

    if not server_id:
        error_exit("Could not find k3s-server instance. Check AWS console.")
    if not agent_id:
        error_exit("Could not find k3s-agent instance. Check AWS console.")

    log_info(f"k3s-server: {server_id}")
    log_info(f"k3s-agent:  {agent_id}")
    print()

    running_count = _count_running_instances()
    check_instance_count(running_count)
    print()

    if not wait_for_ssm(server_id, config):
        error_exit("Server SSM not reachable")
    if not wait_for_ssm(agent_id, config):
        error_exit("Agent SSM not reachable")

    config.server_id = server_id
    config.agent_id = agent_id

    print()
    log_success("All instances are ready via SSM")


def phase2_5_wait_for_tailscale(config):
    print()
    log_info("==========================================")
    log_info("Phase 2.5: Wait for Tailscale Network")
    log_info("==========================================")
    print()

    log_info("Waiting for Tailscale to be running on k3s-server...")
    if not wait_for_tailscale_ip(config.server_id, config):
        error_exit("Tailscale on server not ready")

    log_info("Waiting for Tailscale to be running on k3s-agent...")
    if not wait_for_tailscale_ip(config.agent_id, config):
        error_exit("Tailscale on agent not ready")

    log_success("Tailscale is active on all instances")


def phase3_ansible(config):
    print()
    log_info("==========================================")
    log_info("Phase 3: Kubernetes Cluster (Ansible)")
    log_info("==========================================")
    print()

    inventory_script = Path(config.ansible_dir) / "terraform_inventory_aws.py"
    if not inventory_script.is_file():
        error_exit(f"Dynamic inventory script not found: {inventory_script}")

    log_info("Testing dynamic inventory...")
    rc = subprocess.run(
        ["python3", "terraform_inventory_aws.py", "--list"],
        cwd=config.ansible_dir,
        stdout=subprocess.DEVNULL,
    ).returncode
    if rc != 0:
        error_exit("Inventory script failed")

    log_info("Running Ansible playbook (k3s + ArgoCD + apps) — est. 15-25 min...")
    print()
    rc = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "terraform_inventory_aws.py",
            "playbooks/site.yml",
        ],
        cwd=config.ansible_dir,
    ).returncode
    if rc != 0:
        error_exit("Ansible playbook failed")

    log_success("Kubernetes cluster configured")


def phase4_verify(config):
    print()
    log_info("==========================================")
    log_info("Phase 4: Verification")
    log_info("==========================================")
    print()

    server_id = config.server_id or _describe_instance_id("hl-k3s-server")
    if not server_id:
        log_warning("Could not find server instance for verification — skipping")
        return

    log_info("Checking Kubernetes nodes via SSM...")
    try:
        ssm_run(server_id, "sudo kubectl get nodes -o wide")
    except Exception:
        log_warning("kubectl check failed — cluster may still be initializing")

    log_info("Retrieving kubeconfig via SSM...")
    try:
        kubeconfig_content = ssm_run(server_id, "sudo cat /etc/rancher/k3s/k3s.yaml")
    except Exception:
        kubeconfig_content = ""
    try:
        tailscale_ip = re.sub(r"\s+", "", ssm_run(server_id, "tailscale ip -4") or "")
    except Exception:
        tailscale_ip = ""

    if kubeconfig_content and tailscale_ip:
        rewrite_kubeconfig(kubeconfig_content, tailscale_ip, KUBECONFIG_DEST)
        log_success(f"Kubeconfig saved to {KUBECONFIG_DEST}")
        log_info(f"  export KUBECONFIG={KUBECONFIG_DEST}")
        log_info("  kubectl get nodes")
    else:
        if not kubeconfig_content:
            log_error(
                "Kubeconfig empty — k3s may not have started. "
                "Debug: sudo cat /etc/rancher/k3s/k3s.yaml on the server"
            )
        if not tailscale_ip:
            log_error(
                "Tailscale IP empty — Tailscale may not be connected. "
                "Debug: tailscale status on the server"
            )
        log_warning(
            "Kubeconfig not saved. Re-run 'make verify' once the cluster stabilizes."
        )

    log_success("Verification complete")


# ── destroy ──────────────────────────────────────────────────────────────────


def destroy_infrastructure(config):
    log_warning("Destroying AWS infrastructure...")
    print()
    print("This will:")
    print("  - Terminate all EC2 instances (terminate_instances=true enforced)")
    print("  - Delete EC2 Fleets")
    print("  - Remove Lambda scheduler")
    print()
    confirm = input("Are you sure? Type 'yes' to continue: ")

    if confirm != "yes":
        log_info("Destruction cancelled")
        sys.exit(0)

    log_info("Cleaning up Tailscale ephemeral nodes...")
    rc = subprocess.run(
        ["ansible-playbook", "playbooks/maintenance/cleanup_tailscale.yml"],
        cwd=config.ansible_dir,
    ).returncode
    if rc != 0:
        log_warning(
            "Could not clean up Tailscale nodes. "
            "Manual cleanup may be required in the Tailscale Admin Console."
        )

    rc = subprocess.run(
        ["terraform", "destroy", "-auto-approve"], cwd=config.terraform_dir
    ).returncode
    if rc != 0:
        error_exit("Terraform destroy failed")

    log_success("Infrastructure destroyed")
    sys.exit(0)


# ── banner / summary ─────────────────────────────────────────────────────────


def print_banner():
    print(BLUE, end="")
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║                   AWS HOMELAB DEPLOYMENT                       ║")
    print("║                                                                ║")
    print("║  Terraform → AWS Infrastructure → Ansible → k3s → ArgoCD      ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print(NC)


def print_summary(config):
    print()
    print(
        f"{GREEN}╔════════════════════════════════════════════════════════════════╗{NC}"
    )
    print(
        f"{GREEN}║              DEPLOYMENT COMPLETED SUCCESSFULLY!                ║{NC}"
    )
    print(
        f"{GREEN}╚════════════════════════════════════════════════════════════════╝{NC}"
    )
    print()

    def _tf_output(name):
        result = subprocess.run(
            ["terraform", "output", "-raw", name],
            cwd=config.terraform_dir,
            capture_output=True,
            text=True,
        )
        return parse_terraform_output_raw(result.stdout, result.returncode)

    server_ip = _tf_output("k3s_server_public_ip")
    agent_ip = _tf_output("k3s_agent_public_ip")

    print(f"{BLUE}Instance Information:{NC}")
    print(f"  k3s-server: {server_ip}")
    print(f"  k3s-agent:  {agent_ip}")
    print()
    print(f"{BLUE}Access (Zero Trust — via Tailscale):{NC}")
    print(f"  export KUBECONFIG={KUBECONFIG_DEST}")
    print("  kubectl get nodes")
    print()
    print(f"{BLUE}Access ArgoCD:{NC}")
    print("  kubectl port-forward svc/argocd-server -n argocd 8080:443")
    print("  URL: https://localhost:8080  |  Username: admin")
    print(
        "  Password: kubectl -n argocd get secret argocd-initial-admin-secret "
        "-o jsonpath='{.data.password}' | base64 -d"
    )
    print()
    print(f"{BLUE}Monitor:{NC}")
    print("  kubectl get applications -n argocd")
    print("  kubectl get pods -A")
    print()
    print(f"{BLUE}Destroy:{NC}")
    print("  python3 bin/deploy_aws_homelab.py --destroy")
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────


HELP_EPILOG = """\
Deploy complete AWS homelab infrastructure with k3s, ArgoCD, and applications.
Access model: Zero Trust (Tailscale mesh + SSM). No public SSH ingress.

ENVIRONMENT VARIABLES:
    TERRAFORM_DIR    Path to Terraform directory (default: infra/aws)
    ANSIBLE_DIR      Path to Ansible directory (default: ansible)
    SSH_USER         SSH username (default: ec2-user)
    TIMEOUT          SSM connection timeout in seconds (default: 600)

EXAMPLES:
    python3 bin/deploy_aws_homelab.py            # Deploy everything
    python3 bin/deploy_aws_homelab.py --destroy  # Destroy infrastructure

REQUIREMENTS:
    - Terraform >= 1.0
    - Ansible >= 2.10
    - AWS CLI configured with sufficient permissions
"""


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AWS Homelab deployment orchestrator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    parser.add_argument(
        "--destroy", "-d", action="store_true", help="Destroy all AWS infrastructure"
    )
    args = parser.parse_args(argv)

    print_banner()

    config = DeployConfig()

    if args.destroy:
        destroy_infrastructure(config)
        return 0

    check_prerequisites(config)
    phase1_terraform(config)
    phase2_wait_for_instances(config)
    phase2_5_wait_for_tailscale(config)
    phase3_ansible(config)
    phase4_verify(config)
    print_summary(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
