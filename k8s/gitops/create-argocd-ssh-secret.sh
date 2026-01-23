#!/usr/bin/env bash
# create-argocd-ssh-secret.sh
# Generates ArgoCD repository credential secret for SSH authentication
# Phase 6: Advanced GitOps & App Lifecycle

set -euo pipefail

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# Configuration
readonly NAMESPACE="argocd"
readonly SECRET_NAME="argocd-repo-homelab"
readonly REPO_URL="git@github.com:ariel99gf/homelab.git"
readonly SSH_KEY_PATH="k8s/gitops/ssh/argocd"

# Banner
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ArgoCD SSH Secret Generator - Homelab GitOps Phase 6    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Validation: Check if SSH private key exists
if [[ ! -f "${SSH_KEY_PATH}" ]]; then
    echo -e "${RED}[ERROR]${NC} SSH private key not found at: ${SSH_KEY_PATH}"
    echo ""
    echo "Generate the keypair first:"
    echo "  ssh-keygen -t ed25519 -C 'argocd@homelab-cluster' -f ${SSH_KEY_PATH} -N ''"
    exit 1
fi

echo -e "${GREEN}[✓]${NC} Found SSH private key: ${SSH_KEY_PATH}"

# Validation: Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} kubectl command not found. Install kubectl first."
    exit 1
fi

echo -e "${GREEN}[✓]${NC} kubectl is available"

# Validation: Check if argocd namespace exists
if ! kubectl get namespace "${NAMESPACE}" &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} Namespace '${NAMESPACE}' does not exist. Creating..."
    kubectl create namespace "${NAMESPACE}"
fi

echo -e "${GREEN}[✓]${NC} Namespace '${NAMESPACE}' exists"

# Check if secret already exists
if kubectl get secret "${SECRET_NAME}" -n "${NAMESPACE}" &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} Secret '${SECRET_NAME}' already exists in namespace '${NAMESPACE}'"
    echo ""
    read -p "Do you want to delete and recreate it? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}[INFO]${NC} Deleting existing secret..."
        kubectl delete secret "${SECRET_NAME}" -n "${NAMESPACE}"
    else
        echo -e "${RED}[ABORT]${NC} Secret already exists. Exiting."
        exit 0
    fi
fi

# Create the secret
echo -e "${GREEN}[INFO]${NC} Creating ArgoCD repository secret..."

kubectl create secret generic "${SECRET_NAME}" \
  --namespace="${NAMESPACE}" \
  --from-literal=url="${REPO_URL}" \
  --from-file=sshPrivateKey="${SSH_KEY_PATH}" \
  --dry-run=client -o yaml | \
kubectl apply -f -

# Label the secret so ArgoCD can auto-discover it
echo -e "${GREEN}[INFO]${NC} Labeling secret for ArgoCD auto-discovery..."
kubectl label secret "${SECRET_NAME}" \
  -n "${NAMESPACE}" \
  argocd.argoproj.io/secret-type=repository \
  app.kubernetes.io/name=argocd-repo-homelab \
  app.kubernetes.io/part-of=homelab \
  --overwrite

# Annotate the secret with documentation
kubectl annotate secret "${SECRET_NAME}" \
  -n "${NAMESPACE}" \
  docs.homelab/reference="https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/#ssh-private-key-credential" \
  docs.homelab/created-by="Phase 6: Advanced GitOps & App Lifecycle" \
  --overwrite

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  ✓ Secret Created Successfully             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Display public key for GitHub Deploy Key setup
echo -e "${YELLOW}[ACTION REQUIRED]${NC} Add this public key to GitHub Deploy Keys:"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat "${SSH_KEY_PATH}.pub"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Steps:"
echo "  1. Go to: https://github.com/ariel99gf/homelab/settings/keys/new"
echo "  2. Title: 'ArgoCD Deploy Key (Read-Only)'"
echo "  3. Key: Paste the above public key"
echo "  4. ✗ Allow write access: UNCHECKED (read-only)"
echo "  5. Click 'Add key'"
echo ""

# Verification commands
echo -e "${GREEN}[INFO]${NC} Verification commands:"
echo ""
echo "  # Check if ArgoCD discovered the repository:"
echo "  kubectl get secret ${SECRET_NAME} -n ${NAMESPACE} -o yaml"
echo ""
echo "  # Force ArgoCD to refresh the App-of-Apps:"
echo "  kubectl patch application homelab-apps-root -n ${NAMESPACE} \\"
echo "    --type merge \\"
echo "    -p '{\"metadata\":{\"annotations\":{\"argocd.argoproj.io/refresh\":\"normal\"}}}'"
echo ""
echo "  # Watch application sync status:"
echo "  kubectl get application -n ${NAMESPACE} -w"
echo ""

exit 0
