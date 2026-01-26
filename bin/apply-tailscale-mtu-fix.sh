#!/bin/bash
#
# MTU Fix Application Script
# Purpose: Apply MTU fix (TS_DEBUG_MTU=1100) to resolve packet fragmentation
#
# Root Cause: Pod interface eth0 has MTU 1230, causing fragmentation for 1500-byte packets
# Solution: Force Tailscale to negotiate MTU 1100 (safe margin below 1230)
#
# Author: Senior DevOps Engineer
# Date: 2026-01-25
# Issue: Performance degradation (18 KB/s) caused by MTU fragmentation, NOT CPU throttling
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROXYCLASS_FILE="$REPO_ROOT/k8s/system/tailscale-operator/high-bandwidth-proxyclass.yaml"
PROXYCLASS_NAME="high-bandwidth"
NAMESPACE="tailscale"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}Tailscale MTU Fix Application${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""
echo -e "${BLUE}Root Cause:${NC} Pod interface MTU 1230 causing packet fragmentation"
echo -e "${BLUE}Solution:${NC} Set TS_DEBUG_MTU=1100 to avoid fragmentation"
echo -e "${BLUE}Expected Result:${NC} Throughput increase from 18 KB/s to 500+ KB/s"
echo ""

# Check prerequisites
echo -e "${BLUE}[0] Checking prerequisites...${NC}"

if [ ! -f "$PROXYCLASS_FILE" ]; then
  echo -e "${RED}❌ ProxyClass file not found: $PROXYCLASS_FILE${NC}"
  exit 1
fi

if ! kubectl cluster-info &> /dev/null; then
  echo -e "${RED}❌ Cannot connect to Kubernetes cluster${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Prerequisites check passed${NC}"
echo ""

# Show current MTU configuration
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}[1] Current MTU Configuration${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

# Get first ingress pod
POD_NAME=$(kubectl get pods -n $NAMESPACE -o name | grep "ts-.*-ingress" | head -1 | sed 's|pod/||')

if [ -n "$POD_NAME" ]; then
  echo -e "${BLUE}Checking pod: $POD_NAME${NC}"
  echo ""
  
  echo -e "${YELLOW}Pod interface MTU (eth0):${NC}"
  kubectl exec -n $NAMESPACE $POD_NAME -- ip addr show eth0 | grep mtu || echo "Could not read eth0 MTU"
  
  echo ""
  echo -e "${YELLOW}Tailscale interface MTU (tailscale0):${NC}"
  kubectl exec -n $NAMESPACE $POD_NAME -- ip addr show tailscale0 | grep mtu || echo "tailscale0 not found (normal if pod just started)"
  
  echo ""
else
  echo -e "${YELLOW}⚠️ No ingress pods found (they may have been deleted)${NC}"
  echo ""
fi

# Show current ProxyClass
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}[2] Current ProxyClass Configuration${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

if kubectl get proxyclass $PROXYCLASS_NAME &> /dev/null; then
  echo -e "${BLUE}ProxyClass '$PROXYCLASS_NAME' exists${NC}"
  echo ""
  echo -e "${YELLOW}Current environment variables:${NC}"
  kubectl get proxyclass $PROXYCLASS_NAME -o jsonpath='{.spec.statefulSet.pod.tailscaleContainer.env}' | jq '.' 2>/dev/null || echo "No environment variables set"
  echo ""
else
  echo -e "${YELLOW}ProxyClass '$PROXYCLASS_NAME' does not exist yet${NC}"
  echo ""
fi

# Confirm before applying
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}[3] Apply MTU Fix${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""
echo -e "${YELLOW}This will:${NC}"
echo "  1. Update ProxyClass with TS_DEBUG_MTU=1100"
echo "  2. Delete all Tailscale ingress StatefulSets"
echo "  3. Operator will recreate them with new MTU setting"
echo "  4. Downtime: ~1-2 minutes per ingress"
echo ""
read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
  echo -e "${YELLOW}Operation cancelled${NC}"
  exit 0
fi

echo ""

# Apply updated ProxyClass
echo -e "${BLUE}Step 1: Applying updated ProxyClass...${NC}"
kubectl apply -f $PROXYCLASS_FILE

if [ $? -eq 0 ]; then
  echo -e "${GREEN}✓ ProxyClass updated successfully${NC}"
else
  echo -e "${RED}❌ Failed to update ProxyClass${NC}"
  exit 1
fi

echo ""

# Verify TS_DEBUG_MTU is set
echo -e "${BLUE}Step 2: Verifying TS_DEBUG_MTU configuration...${NC}"
MTU_VALUE=$(kubectl get proxyclass $PROXYCLASS_NAME -o jsonpath='{.spec.statefulSet.pod.tailscaleContainer.env[?(@.name=="TS_DEBUG_MTU")].value}')

if [ "$MTU_VALUE" = "1100" ]; then
  echo -e "${GREEN}✓ TS_DEBUG_MTU is set to 1100${NC}"
else
  echo -e "${RED}❌ TS_DEBUG_MTU is not set correctly (value: $MTU_VALUE)${NC}"
  exit 1
fi

echo ""

# Delete StatefulSets to force recreation
echo -e "${BLUE}Step 3: Deleting Tailscale ingress StatefulSets...${NC}"
echo -e "${YELLOW}This triggers operator to recreate them with new MTU setting${NC}"
echo ""

STATEFULSETS=$(kubectl get statefulset -n $NAMESPACE -o name | grep "ts-.*-ingress")

if [ -z "$STATEFULSETS" ]; then
  echo -e "${YELLOW}⚠️ No StatefulSets found (may already be deleted)${NC}"
else
  echo "$STATEFULSETS" | xargs kubectl delete -n $NAMESPACE
  echo -e "${GREEN}✓ StatefulSets deleted${NC}"
fi

echo ""

# Wait for recreation
echo -e "${BLUE}Step 4: Waiting for StatefulSets to be recreated...${NC}"
echo -e "${YELLOW}Operator will recreate StatefulSets with new MTU setting (90 seconds)${NC}"
sleep 90

echo ""

# Check new StatefulSets
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}[4] Verification${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

echo -e "${BLUE}StatefulSet status:${NC}"
kubectl get statefulset -n $NAMESPACE

echo ""

echo -e "${BLUE}Pod status:${NC}"
kubectl get pods -n $NAMESPACE | grep -E "NAME|ingress"

echo ""

# Check MTU on new pods
echo -e "${BLUE}Waiting 30 more seconds for pods to be fully ready...${NC}"
sleep 30

NEW_POD_NAME=$(kubectl get pods -n $NAMESPACE -o name | grep "ts-.*-ingress" | head -1 | sed 's|pod/||')

if [ -n "$NEW_POD_NAME" ]; then
  echo ""
  echo -e "${BLUE}Checking MTU on new pod: $NEW_POD_NAME${NC}"
  echo ""
  
  echo -e "${YELLOW}Tailscale interface MTU (should be ~1100):${NC}"
  kubectl exec -n $NAMESPACE $NEW_POD_NAME -- ip addr show tailscale0 2>/dev/null | grep mtu || echo "tailscale0 not ready yet (normal, may take 1-2 minutes)"
  
  echo ""
  
  # Check environment variable
  echo -e "${YELLOW}TS_DEBUG_MTU environment variable:${NC}"
  kubectl exec -n $NAMESPACE $NEW_POD_NAME -- sh -c 'echo $TS_DEBUG_MTU' 2>/dev/null || echo "Could not read environment variable"
  
  echo ""
fi

# Success message
echo -e "${CYAN}==========================================${NC}"
echo -e "${GREEN}✓ MTU Fix Applied Successfully${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Wait 2-3 minutes for all pods to fully initialize"
echo ""
echo "2. Test performance (should see dramatic improvement):"
echo "   time curl -o /dev/null https://adguard.tail57bf10.ts.net/login.*.js"
echo ""
echo "3. Expected results:"
echo "   Before: 139 seconds @ 18 KB/s"
echo "   After:  <10 seconds @ 250+ KB/s"
echo "   Improvement: 10-25x faster!"
echo ""
echo "4. Verify MTU on Tailscale interface:"
echo "   kubectl exec -n $NAMESPACE $NEW_POD_NAME -- ip addr show tailscale0 | grep mtu"
echo "   Should show: mtu 1100"
echo ""
echo "5. If performance doesn't improve, check diagnostic:"
echo "   ./.opencode/tailscale-diagnostic.sh YOUR_TAILSCALE_IP"
echo ""
echo -e "${CYAN}==========================================${NC}"
echo ""
echo -e "${YELLOW}Commit Changes:${NC}"
echo ""
echo "Once performance is verified, commit the ProxyClass change:"
echo ""
echo "  git add k8s/system/tailscale-operator/high-bandwidth-proxyclass.yaml"
echo "  git commit -m 'fix: add MTU 1100 to ProxyClass to prevent fragmentation'"
echo "  git push origin fix/tailscale-ingress-performance-v2"
echo ""
echo -e "${CYAN}==========================================${NC}"
echo ""
