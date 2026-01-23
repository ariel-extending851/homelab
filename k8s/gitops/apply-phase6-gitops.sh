#!/usr/bin/env bash
# apply-phase6-gitops.sh
# Orchestrates Phase 6: ArgoCD SSH Migration & GitOps Optimization
# Resolves OCI egress throttling by transitioning from HTTPS to SSH

set -euo pipefail

# Color codes
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

# Configuration
readonly NAMESPACE="argocd"
readonly APP_NAME="homelab-apps-root"
# SC2155: Declare and assign separately to avoid masking return values
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

# Banner
clear
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Phase 6: Advanced GitOps & App Lifecycle              ║${NC}"
echo -e "${BLUE}║     ArgoCD SSH Authentication Migration                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Pre-flight checks
echo -e "${GREEN}[STEP 1/6]${NC} Pre-flight Validation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check kubectl
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} kubectl not found. Install kubectl first."
    exit 1
fi
echo -e "${GREEN}[✓]${NC} kubectl is available"

# Check if ArgoCD namespace exists
if ! kubectl get namespace "${NAMESPACE}" &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Namespace '${NAMESPACE}' not found. Install ArgoCD first."
    exit 1
fi
echo -e "${GREEN}[✓]${NC} ArgoCD namespace exists"

# Check if App-of-Apps exists
if ! kubectl get application "${APP_NAME}" -n "${NAMESPACE}" &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Application '${APP_NAME}' not found. Create it first."
    exit 1
fi
echo -e "${GREEN}[✓]${NC} App-of-Apps '${APP_NAME}' exists"

echo ""

# Step 2: Display public key for GitHub
echo -e "${GREEN}[STEP 2/6]${NC} GitHub Deploy Key Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -f "${SCRIPT_DIR}/ssh/argocd.pub" ]]; then
    echo ""
    echo -e "${YELLOW}[ACTION REQUIRED]${NC} Add this public key to GitHub Deploy Keys:"
    echo ""
    echo "┌────────────────────────────────────────────────────────────┐"
    cat "${SCRIPT_DIR}/ssh/argocd.pub"
    echo "└────────────────────────────────────────────────────────────┘"
    echo ""
    echo "Instructions:"
    echo "  1. Go to: https://github.com/ariel99gf/homelab/settings/keys/new"
    echo "  2. Title: 'ArgoCD Deploy Key (Read-Only)'"
    echo "  3. Key: Paste the above public key"
    echo "  4. ✗ Allow write access: UNCHECKED (read-only)"
    echo "  5. Click 'Add key'"
    echo ""
    read -p "Have you added the Deploy Key to GitHub? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}[ABORT]${NC} Deploy Key not added. Exiting."
        exit 1
    fi
    echo -e "${GREEN}[✓]${NC} Deploy Key confirmed"
else
    echo -e "${RED}[ERROR]${NC} SSH public key not found at: ${SCRIPT_DIR}/ssh/argocd.pub"
    echo ""
    echo "Generate the keypair first:"
    echo "  ssh-keygen -t ed25519 -C 'argocd@homelab-cluster' \\"
    echo "    -f k8s/gitops/ssh/argocd -N ''"
    exit 1
fi

echo ""

# Step 3: Create ArgoCD repository secret
echo -e "${GREEN}[STEP 3/6]${NC} Create ArgoCD Repository Secret"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -f "${SCRIPT_DIR}/create-argocd-ssh-secret.sh" ]]; then
    echo -e "${BLUE}[INFO]${NC} Executing: ${SCRIPT_DIR}/create-argocd-ssh-secret.sh"
    "${SCRIPT_DIR}/create-argocd-ssh-secret.sh"
else
    echo -e "${RED}[ERROR]${NC} Secret creation script not found!"
    exit 1
fi

echo ""

# Step 4: Update App-of-Apps manifest
echo -e "${GREEN}[STEP 4/6]${NC} Update App-of-Apps Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${BLUE}[INFO]${NC} Applying updated apps-root.yaml..."
kubectl apply -f "${SCRIPT_DIR}/apps-root.yaml"

echo -e "${GREEN}[✓]${NC} App-of-Apps updated to SSH URL (git@github.com:ariel99gf/homelab.git)"
echo -e "${GREEN}[✓]${NC} Target branch changed to 'develop'"

echo ""

# Step 5: Force ArgoCD refresh
echo -e "${GREEN}[STEP 5/6]${NC} Force ArgoCD Refresh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${BLUE}[INFO]${NC} Triggering ArgoCD refresh for '${APP_NAME}'..."
kubectl patch application "${APP_NAME}" -n "${NAMESPACE}" \
  --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'

echo -e "${GREEN}[✓]${NC} Refresh triggered"

echo ""

# Step 6: Verify synchronization
echo -e "${GREEN}[STEP 6/6]${NC} Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${BLUE}[INFO]${NC} Waiting 10 seconds for ArgoCD to process..."
sleep 10

echo ""
echo "Application Status:"
kubectl get application -n "${NAMESPACE}" -o wide

echo ""
echo -e "${YELLOW}[INFO]${NC} Monitoring commands:"
echo ""
echo "  # Watch application sync status in real-time:"
echo "  kubectl get application -n ${NAMESPACE} -w"
echo ""
echo "  # Check ArgoCD server logs:"
echo "  kubectl logs -n ${NAMESPACE} deployment/argocd-server --tail=50 -f"
echo ""
echo "  # Check repository connection status:"
echo "  kubectl logs -n ${NAMESPACE} deployment/argocd-repo-server --tail=50"
echo ""

# Summary
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            ✓ Phase 6 Migration Completed                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Changes Applied:${NC}"
echo "  • SSH keypair generated (ED25519, 256-bit)"
echo "  • GitHub Deploy Key configured (read-only)"
echo "  • ArgoCD repository secret created"
echo "  • App-of-Apps updated to SSH URL"
echo "  • Target branch changed to 'develop'"
echo "  • Automated sync enabled (selfHeal: true, prune: true)"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Monitor ArgoCD sync status (commands above)"
echo "  2. Verify all applications reach 'Healthy' and 'Synced' state"
echo "  3. Update .opencode/plan.md with Phase 6 completion"
echo "  4. Consider Helm migration for ArgoCD base installation (optional)"
echo ""

exit 0
