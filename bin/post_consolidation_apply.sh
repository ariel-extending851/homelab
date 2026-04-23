#!/usr/bin/env bash
# post_consolidation_apply.sh
#
# One-shot script to run the post-merge actions for the docs consolidation PR:
#   1. Verify the ArgoCD SSH deploy key is registered on the canonical repo
#   2. Plan + apply the OIDC trust-policy URL change in AWS IAM
#   3. Refresh kubeconfig + validate ArgoCD picks up the new apps-root.yaml
#
# Safe to re-run; each step prompts before mutating anything.
# Delete this script after the migration is fully landed.

set -euo pipefail

# ─── colors ─────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED=$(tput setaf 1); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3)
  BLUE=$(tput setaf 4); BOLD=$(tput bold); RESET=$(tput sgr0)
else
  RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; RESET=""
fi

step() { echo; echo "${BOLD}${BLUE}▶ $1${RESET}"; }
ok()   { echo "${GREEN}✓${RESET} $1"; }
warn() { echo "${YELLOW}⚠${RESET}  $1"; }
fail() { echo "${RED}✗${RESET} $1" >&2; exit 1; }

confirm() {
  local prompt="$1"
  read -r -p "${BOLD}${prompt}${RESET} [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { warn "aborted by user"; exit 1; }
}

# ─── working directory ──────────────────────────────────────────────────
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)" \
  || fail "must run from inside the homelab git repo"
cd "$REPO_ROOT"

CANONICAL_REPO="ariel-extending851/homelab"

# ═══════════════════════════════════════════════════════════════════════
# Pre-flight checks
# ═══════════════════════════════════════════════════════════════════════

step "Pre-flight checks"

# Are we on the right branch with the changes?
current_branch=$(git rev-parse --abbrev-ref HEAD)
echo "  current branch: ${current_branch}"

# Does the canonical URL actually appear in the code?
grep -q "${CANONICAL_REPO}" infra/aws-oidc/main.tf 2>/dev/null \
  || fail "infra/aws-oidc/main.tf does not target ${CANONICAL_REPO} — has commit 1 landed?"
ok "Terraform OIDC code targets ${CANONICAL_REPO}"

grep -q "${CANONICAL_REPO}" k8s/gitops/apps-root.yaml 2>/dev/null \
  || fail "k8s/gitops/apps-root.yaml does not target ${CANONICAL_REPO}"
ok "ArgoCD apps-root targets ${CANONICAL_REPO}"

# Is mise available?
command -v mise >/dev/null 2>&1 || fail "mise not installed (see docs/getting-started/prerequisites.md)"
ok "mise available"

# AWS credentials? (uses AWS_PROFILE from .mise.toml — currently 'Homelab')
if ! mise exec -- aws sts get-caller-identity >/dev/null 2>&1; then
  AWSP=$(mise env 2>/dev/null | grep -oP 'AWS_PROFILE=\K\S+' || echo '<unset>')
  fail "AWS profile '${AWSP}' not authenticated (check ~/.aws/credentials)"
fi
ACCT=$(mise exec -- aws sts get-caller-identity --query Account --output text)
ARN=$(mise exec -- aws sts get-caller-identity --query Arn --output text)
ok "AWS authenticated — account: ${ACCT}, identity: ${ARN}"

# ═══════════════════════════════════════════════════════════════════════
# Step 1 — Confirm the ArgoCD SSH deploy key is on the canonical repo
# ═══════════════════════════════════════════════════════════════════════

step "Step 1/3 — Confirm ArgoCD SSH deploy key is on ${CANONICAL_REPO}"

cat <<EOF
The ArgoCD repo-server uses the SSH key in k8s/gitops/ssh/argocd to
authenticate with GitHub. After the URL change, this key MUST be
registered as a deploy key on:

  ${BOLD}https://github.com/${CANONICAL_REPO}/settings/keys${RESET}

If it isn't, ArgoCD will fail to clone with 'Permission denied (publickey)'
once it tries to refresh against the new URL.

Public key to verify in GitHub:
EOF

if [[ -f k8s/gitops/ssh/argocd.pub ]]; then
  echo "${GREEN}---${RESET}"
  cat k8s/gitops/ssh/argocd.pub
  echo "${GREEN}---${RESET}"
else
  warn "k8s/gitops/ssh/argocd.pub not found locally — check your workstation"
fi

confirm "Have you confirmed this exact public key is on the canonical repo?"
ok "deploy key registration confirmed"

# ═══════════════════════════════════════════════════════════════════════
# Step 2 — OIDC trust policy plan + apply
# ═══════════════════════════════════════════════════════════════════════

step "Step 2/3 — Update AWS IAM OIDC trust policy"

echo "Running: make oidc-plan"
echo
mise exec -- make oidc-plan

echo
warn "Review the plan above. The expected change is the trust policy"
warn "'sub' condition: 'repo:ariel99gf/homelab:*' → 'repo:${CANONICAL_REPO}:*'"
echo
confirm "Apply this change to AWS IAM?"

mise exec -- make oidc-apply
ok "OIDC trust policy updated"

# Show the new role ARN for sanity
echo
echo "New OIDC role ARN (paste into GitHub Actions if needed):"
mise exec -- make oidc-output

# ═══════════════════════════════════════════════════════════════════════
# Step 3 — Refresh kubeconfig + validate ArgoCD sync
# ═══════════════════════════════════════════════════════════════════════

step "Step 3/3 — Validate ArgoCD picks up the new repoURL"

echo "Refreshing local kubeconfig..."
mise exec -- make k8s-kubeconfig
ok "kubeconfig refreshed"

# Confirm cluster reachable
if ! mise exec -- kubectl get nodes --request-timeout=10s >/dev/null 2>&1; then
  warn "cluster not reachable via kubectl — Tailscale auth issue?"
  warn "see docs/runbooks/tailscale-logged-out.md"
  fail "cannot proceed without cluster access"
fi
ok "cluster reachable"

# Force ArgoCD to refresh against the new URL
echo
echo "Forcing ArgoCD to refresh apps-root..."
mise exec -- kubectl patch application homelab-apps-root -n argocd --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'

# Wait for sync
echo
echo "Waiting for apps-root to reach Synced + Healthy..."
mise exec -- make validate-argocd-synced

# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════

step "All steps completed"

cat <<EOF
${GREEN}✓ AWS IAM trust policy now targets ${CANONICAL_REPO}${RESET}
${GREEN}✓ ArgoCD apps-root is Synced + Healthy on the new repoURL${RESET}

Next: nothing required. The migration is complete.

Optional cleanup:
  - Delete this script:  rm bin/post_consolidation_apply.sh
  - Run \`pre-commit install\` if you haven't already (commit 4)

Spot-check from a browser:
  - Open https://grafana.tail57bf10.ts.net (any tailnet host)
  - kubectl get applications -n argocd  (all should be Synced + Healthy)
EOF
