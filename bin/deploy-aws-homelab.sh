#!/bin/bash
# AWS Homelab - Full Deployment Script
# Purpose: Deploy complete AWS infrastructure + k3s cluster + ArgoCD + apps
# Usage: ./bin/deploy-aws-homelab.sh [--destroy]
#
# Access model: Zero Trust (Tailscale + SSM). No public SSH required.

set -euo pipefail

# Configuration
TERRAFORM_DIR="${TERRAFORM_DIR:-infra/aws}"
ANSIBLE_DIR="${ANSIBLE_DIR:-ansible}"
SSH_USER="${SSH_USER:-ec2-user}"
TIMEOUT="${TIMEOUT:-600}" # 10 minutes max wait for SSM/Tailscale

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error_exit() {
  log_error "$1"
  exit 1
}

# Guard against orphan EC2 instances — expects exactly 2 (server + agent).
# Usage: check_instance_count <count>
check_instance_count() {
  local count=$1
  if [ "$count" -gt 2 ]; then
    log_error "Found $count instances running (expected 2). Aborting to prevent orphans."
    log_error "Run: aws ec2 describe-instances --filters Name=instance-state-name,Values=running"
    error_exit "Manual cleanup required before re-deploying."
  fi
  log_success "Instance count verified: $count/2"
}

# Rewrite kubeconfig: replace 127.0.0.1 with the Tailscale IP and save with 0600 perms.
# Usage: rewrite_kubeconfig <kubeconfig_content> <tailscale_ip> <dest_path>
rewrite_kubeconfig() {
  local content="$1"
  local tailscale_ip="$2"
  local dest="$3"
  # shellcheck disable=SC2001
  echo "$content" | sed "s|127.0.0.1|${tailscale_ip}|g" > "$dest"
  chmod 600 "$dest"
}

print_banner() {
  echo -e "${BLUE}"
  cat <<'EOF'
╔════════════════════════════════════════════════════════════════╗
║                   AWS HOMELAB DEPLOYMENT                       ║
║                                                                ║
║  Terraform → AWS Infrastructure → Ansible → k3s → ArgoCD      ║
╚════════════════════════════════════════════════════════════════╝
EOF
  echo -e "${NC}"
}

# Check prerequisites
check_prerequisites() {
  log_info "Checking prerequisites..."

  command -v terraform &>/dev/null || error_exit "Terraform not found."
  command -v ansible-playbook &>/dev/null || error_exit "Ansible not found. Install: pip3 install ansible"
  command -v aws &>/dev/null || error_exit "AWS CLI not found."

  [ -d "$TERRAFORM_DIR" ] || error_exit "Terraform directory not found: $TERRAFORM_DIR"
  [ -d "$ANSIBLE_DIR" ] || error_exit "Ansible directory not found: $ANSIBLE_DIR"

  check_sops_key

  log_success "All prerequisites met"
}

# Verify SOPS Age key is configured and can decrypt secrets
check_sops_key() {
  command -v sops &>/dev/null || error_exit "sops not found. Install: https://github.com/getsops/sops"

  local key_configured=false
  [ -n "${SOPS_AGE_KEY_FILE:-}" ] && [ -f "${SOPS_AGE_KEY_FILE}" ] && key_configured=true
  [ -n "${SOPS_AGE_KEY:-}" ] && key_configured=true

  $key_configured || error_exit "Age key not configured. Set SOPS_AGE_KEY_FILE or SOPS_AGE_KEY env var."

  sops --decrypt k8s/apps/adguard/secret.yaml >/dev/null 2>&1 \
    || error_exit "SOPS decryption failed. Verify your Age key can decrypt k8s/apps/adguard/secret.yaml."

  log_success "SOPS decryption verified"
}

# Wait for SSM agent to register on an instance
# Usage: wait_for_ssm <instance-id>
wait_for_ssm() {
  local instance_id=$1
  local max_attempts=$((TIMEOUT / 15))
  local attempt=0

  log_info "Waiting for SSM agent on $instance_id..."

  while [ $attempt -lt $max_attempts ]; do
    STATUS=$(aws ssm describe-instance-information \
      --filters "Key=InstanceIds,Values=$instance_id" \
      --query "InstanceInformationList[0].PingStatus" \
      --output text 2>/dev/null || echo "None")

    if [ "$STATUS" = "Online" ]; then
      log_success "SSM ready on $instance_id"
      return 0
    fi

    echo -n "."
    sleep 15
    attempt=$((attempt + 1))
  done

  log_error "Timeout waiting for SSM on $instance_id after $TIMEOUT seconds"
  return 1
}

# Run a command on an instance via SSM and return output
# Usage: ssm_run <instance-id> <command>
ssm_run() {
  local instance_id=$1
  local command=$2
  local i=0

  CMD_ID=$(aws ssm send-command \
    --instance-ids "$instance_id" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[\"$command\"]" \
    --query "Command.CommandId" \
    --output text)

  while [ $i -lt 15 ]; do
    sleep 3
    STATUS=$(aws ssm get-command-invocation \
      --command-id "$CMD_ID" \
      --instance-id "$instance_id" \
      --query "Status" --output text 2>/dev/null || echo "Pending")
    if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then break; fi
    i=$((i + 1))
  done

  aws ssm get-command-invocation \
    --command-id "$CMD_ID" \
    --instance-id "$instance_id" \
    --query "StandardOutputContent" \
    --output text
}

# Destroy infrastructure
destroy_infrastructure() {
  log_warning "Destroying AWS infrastructure..."
  echo ""
  echo "This will:"
  echo "  - Terminate all EC2 instances (terminate_instances=true enforced)"
  echo "  - Delete EC2 Fleets"
  echo "  - Remove Lambda scheduler"
  echo ""
  read -rp "Are you sure? Type 'yes' to continue: " confirm

  [ "$confirm" = "yes" ] || {
    log_info "Destruction cancelled"
    exit 0
  }

  log_info "Cleaning up Tailscale ephemeral nodes..."
  (cd "$ANSIBLE_DIR" && ansible-playbook playbooks/maintenance/cleanup_tailscale.yml) ||
    log_warning "Could not clean up Tailscale nodes. Manual cleanup may be required in the Tailscale Admin Console."

  (cd "$TERRAFORM_DIR" && terraform destroy -auto-approve) || error_exit "Terraform destroy failed"
  log_success "Infrastructure destroyed"
  exit 0
}

# Phase 1: Terraform
phase1_terraform() {
  echo ""
  log_info "=========================================="
  log_info "Phase 1: AWS Infrastructure (Terraform)"
  log_info "=========================================="
  echo ""

  log_info "Initializing Terraform..."
  (cd "$TERRAFORM_DIR" && terraform init -upgrade) || error_exit "Terraform init failed"

  log_info "Validating Terraform configuration..."
  (cd "$TERRAFORM_DIR" && terraform validate) || error_exit "Terraform validation failed"

  log_info "Checking if Tailscale ACL needs to be imported..."
  if ! (cd "$TERRAFORM_DIR" && terraform state list | grep -q "tailscale_acl.homelab_acl"); then
    log_warning "ACL not found in state. Attempting import..."
    (cd "$TERRAFORM_DIR" && terraform import tailscale_acl.homelab_acl acl) || log_warning "Import failed (non-fatal)."
  else
    log_success "Tailscale ACL is already managed by Terraform"
  fi

  log_info "Applying Terraform configuration..."
  (cd "$TERRAFORM_DIR" && terraform apply -auto-approve) || error_exit "Terraform apply failed"

  # Refresh state after apply so data sources (instance IPs) are accurate.
  # EC2 Fleets assign instances asynchronously — refresh resolves the timing gap.
  log_info "Refreshing state to capture live instance IPs..."
  (cd "$TERRAFORM_DIR" && terraform apply -refresh-only -auto-approve) ||
    log_warning "Refresh-only pass failed — outputs may show empty IPs (non-fatal)"

  log_success "AWS infrastructure created"
}

# Phase 2: Wait for instances via SSM (Zero Trust — no public SSH)
phase2_wait_for_instances() {
  echo ""
  log_info "=========================================="
  log_info "Phase 2: Wait for EC2 Instances (SSM)"
  log_info "=========================================="
  echo ""

  log_info "Retrieving instance IDs from AWS..."

  SERVER_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=hl-k3s-server" \
    "Name=instance-state-name,Values=pending,running" \
    --query "Reservations[0].Instances[0].InstanceId" \
    --output text 2>/dev/null || echo "")

  AGENT_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=hl-k3s-agent" \
    "Name=instance-state-name,Values=pending,running" \
    --query "Reservations[0].Instances[0].InstanceId" \
    --output text 2>/dev/null || echo "")

  [ -n "$SERVER_ID" ] || error_exit "Could not find k3s-server instance. Check AWS console."
  [ -n "$AGENT_ID" ] || error_exit "Could not find k3s-agent instance. Check AWS console."

  log_info "k3s-server: $SERVER_ID"
  log_info "k3s-agent:  $AGENT_ID"
  echo ""

  # Confirm only 2 instances are running — guard against orphan regressions
  RUNNING_COUNT=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=hl-k3s-server,hl-k3s-agent" \
    "Name=instance-state-name,Values=pending,running" \
    --query "length(Reservations[*].Instances[*])" \
    --output text)

  check_instance_count "$RUNNING_COUNT"
  echo ""

  # Wait for SSM on both
  wait_for_ssm "$SERVER_ID" || error_exit "Server SSM not reachable"
  wait_for_ssm "$AGENT_ID" || error_exit "Agent SSM not reachable"

  # Export for use in subsequent phases
  export K3S_SERVER_ID="$SERVER_ID"
  export K3S_AGENT_ID="$AGENT_ID"

  echo ""
  log_success "All instances are ready via SSM"
}

# Phase 2.5: Wait for Tailscale to be fully running on instances
phase2_5_wait_for_tailscale() {
  echo ""
  log_info "=========================================="
  log_info "Phase 2.5: Wait for Tailscale Network"
  log_info "=========================================="
  echo ""

  log_info "Waiting for Tailscale to be running on k3s-server..."
  wait_for_tailscale_ip "${K3S_SERVER_ID}" || error_exit "Tailscale on server not ready"

  log_info "Waiting for Tailscale to be running on k3s-agent..."
  wait_for_tailscale_ip "${K3S_AGENT_ID}" || error_exit "Tailscale on agent not ready"

  log_success "Tailscale is active on all instances"
}

# Helper function to check for a Tailscale IP
# Usage: wait_for_tailscale_ip <instance-id>
wait_for_tailscale_ip() {
  local instance_id=$1
  local max_attempts=$((TIMEOUT / 10))
  local attempt=0

  while [ $attempt -lt $max_attempts ]; do
    TS_IP=$(ssm_run "$instance_id" "tailscale ip -4" 2>/dev/null | tr -d '[:space:]' || echo "")
    if [[ "$TS_IP" =~ ^100\. ]]; then
      log_success "Tailscale IP found for $instance_id: $TS_IP"
      return 0
    fi
    echo -n "."
    sleep 10
    attempt=$((attempt + 1))
  done

  log_error "Timeout waiting for Tailscale IP on $instance_id after $TIMEOUT seconds"
  return 1
}

# Phase 3: Ansible — Configure k3s cluster
phase3_ansible() {
  echo ""
  log_info "=========================================="
  log_info "Phase 3: Kubernetes Cluster (Ansible)"
  log_info "=========================================="
  echo ""

  [ -f "$ANSIBLE_DIR/terraform_inventory_aws.py" ] ||
    error_exit "Dynamic inventory script not found: $ANSIBLE_DIR/terraform_inventory_aws.py"

  log_info "Testing dynamic inventory..."
  (cd "$ANSIBLE_DIR" && python3 terraform_inventory_aws.py --list >/dev/null) ||
    error_exit "Inventory script failed"

  log_info "Running Ansible playbook (k3s + ArgoCD + apps) — est. 15-25 min..."
  echo ""

  (cd "$ANSIBLE_DIR" && ansible-playbook \
    -i terraform_inventory_aws.py \
    playbooks/site.yml) || error_exit "Ansible playbook failed"

  log_success "Kubernetes cluster configured"
}

# Phase 4: Verification via SSM (no SSH keys needed)
phase4_verify() {
  echo ""
  log_info "=========================================="
  log_info "Phase 4: Verification"
  log_info "=========================================="
  echo ""

  local server_id="${K3S_SERVER_ID:-}"

  if [ -z "$server_id" ]; then
    server_id=$(aws ec2 describe-instances \
      --filters "Name=tag:Name,Values=hl-k3s-server" \
      "Name=instance-state-name,Values=running" \
      --query "Reservations[0].Instances[0].InstanceId" \
      --output text 2>/dev/null || echo "")
  fi

  if [ -z "$server_id" ]; then
    log_warning "Could not find server instance for verification — skipping"
    return
  fi

  log_info "Checking Kubernetes nodes via SSM..."
  ssm_run "$server_id" "sudo kubectl get nodes -o wide" ||
    log_warning "kubectl check failed — cluster may still be initializing"

  log_info "Retrieving kubeconfig via SSM..."
  KUBECONFIG_CONTENT=$(ssm_run "$server_id" "sudo cat /etc/rancher/k3s/k3s.yaml" 2>/dev/null || echo "")
  TAILSCALE_IP=$(ssm_run "$server_id" "tailscale ip -4" 2>/dev/null | tr -d '[:space:]' || echo "")

  if [ -n "$KUBECONFIG_CONTENT" ] && [ -n "$TAILSCALE_IP" ]; then
    rewrite_kubeconfig "$KUBECONFIG_CONTENT" "$TAILSCALE_IP" /tmp/k3s-homelab-kubeconfig.yaml
    log_success "Kubeconfig saved to /tmp/k3s-homelab-kubeconfig.yaml"
    log_info "  export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml"
    log_info "  kubectl get nodes"
  else
    [ -z "$KUBECONFIG_CONTENT" ] && log_error "Kubeconfig empty — k3s may not have started. Debug: sudo cat /etc/rancher/k3s/k3s.yaml on the server"
    [ -z "$TAILSCALE_IP" ] && log_error "Tailscale IP empty — Tailscale may not be connected. Debug: tailscale status on the server"
    log_warning "Kubeconfig not saved. Re-run 'make verify' once the cluster stabilizes."
  fi

  log_success "Verification complete"
}

print_summary() {
  echo ""
  echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║              DEPLOYMENT COMPLETED SUCCESSFULLY!                ║${NC}"
  echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
  echo ""

  SERVER_IP=$(cd "$TERRAFORM_DIR" && terraform output -raw k3s_server_public_ip 2>/dev/null || echo "N/A")
  AGENT_IP=$(cd "$TERRAFORM_DIR" && terraform output -raw k3s_agent_public_ip 2>/dev/null || echo "N/A")

  echo -e "${BLUE}Instance Information:${NC}"
  echo "  k3s-server: $SERVER_IP"
  echo "  k3s-agent:  $AGENT_IP"
  echo ""
  echo -e "${BLUE}Access (Zero Trust — via Tailscale):${NC}"
  echo "  export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml"
  echo "  kubectl get nodes"
  echo ""
  echo -e "${BLUE}Access ArgoCD:${NC}"
  echo "  kubectl port-forward svc/argocd-server -n argocd 8080:443"
  echo "  URL: https://localhost:8080  |  Username: admin"
  echo "  Password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
  echo ""
  echo -e "${BLUE}Monitor:${NC}"
  echo "  kubectl get applications -n argocd"
  echo "  kubectl get pods -A"
  echo ""
  echo -e "${BLUE}Destroy:${NC}"
  echo "  ./bin/deploy-aws-homelab.sh --destroy"
  echo ""
}

# Main execution
main() {
  print_banner

  case "${1:-}" in
  --destroy | -d)
    destroy_infrastructure
    ;;
  --help | -h)
    cat <<EOF
Usage: $0 [OPTIONS]

Deploy complete AWS homelab infrastructure with k3s, ArgoCD, and applications.
Access model: Zero Trust (Tailscale mesh + SSM). No public SSH ingress.

OPTIONS:
    --destroy, -d    Destroy all AWS infrastructure
    --help, -h       Show this help message

ENVIRONMENT VARIABLES:
    TERRAFORM_DIR    Path to Terraform directory (default: infra/aws)
    ANSIBLE_DIR      Path to Ansible directory (default: ansible)
    SSH_USER         SSH username (default: ec2-user)
    TIMEOUT          SSM connection timeout in seconds (default: 600)

EXAMPLES:
    ./bin/deploy-aws-homelab.sh            # Deploy everything
    ./bin/deploy-aws-homelab.sh --destroy  # Destroy infrastructure

REQUIREMENTS:
    - Terraform >= 1.0
    - Ansible >= 2.10
    - AWS CLI configured with sufficient permissions
EOF
    exit 0
    ;;
  esac

  check_prerequisites
  phase1_terraform
  phase2_wait_for_instances
  phase2_5_wait_for_tailscale
  phase3_ansible
  phase4_verify
  print_summary
}

# Allow sourcing for unit tests without running main.
[[ "${BASH_SOURCE[0]}" != "${0}" ]] || main "$@"
