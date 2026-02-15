#!/bin/bash
# ROLLBACK SCRIPT - Emergency recovery for proxy migration
# Run this if proxy migration causes issues

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================="
echo -e "${RED}EMERGENCY ROLLBACK SCRIPT${NC}"
echo "========================================="
echo ""
echo "This will:"
echo "1. Uncordon RPi 4 (if cordoned)"
echo "2. Restart Tailscale operator"
echo "3. Force recreation of all proxies"
echo ""
echo -e "${YELLOW}WARNING: This will cause 1-2 minutes of downtime${NC}"
echo ""

read -p "Proceed with rollback? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "=== Step 1: Ensuring RPi 4 is uncordoned ==="
kubectl uncordon rasp-pi-04 2>/dev/null || echo "Already uncordoned or not cordoned"
echo -e "${GREEN}✓ RPi 4 uncordoned${NC}"
echo ""

echo "=== Step 2: Current proxy state ==="
kubectl get pods -n tailscale -o wide | grep ingress || echo "No ingress proxies"
echo ""

echo "=== Step 3: Restarting Tailscale operator ==="
kubectl rollout restart deployment -n tailscale operator
echo "Waiting for operator to be ready..."
kubectl rollout status deployment -n tailscale operator --timeout=60s
echo -e "${GREEN}✓ Operator restarted${NC}"
echo ""

echo "=== Step 4: Force recreation of all proxy pods ==="
PROXY_PODS=$(kubectl get pods -n tailscale -o name | grep ingress || true)

if [ -n "$PROXY_PODS" ]; then
    echo "Deleting all proxy pods for recreation..."
    kubectl delete -n tailscale $PROXY_PODS --grace-period=10
    echo -e "${GREEN}✓ Pods deleted${NC}"
else
    echo "No proxy pods found"
fi

echo ""
echo "=== Step 5: Waiting for recreation ==="
echo "Waiting for all proxies to be Ready (up to 3 minutes)..."
if kubectl wait --for=condition=Ready pods -n tailscale -l tailscale.com/proxy-class=default --timeout=180s; then
    echo -e "${GREEN}✓ All proxies Ready${NC}"
else
    echo -e "${YELLOW}⚠ Timeout waiting for pods${NC}"
fi

echo ""
echo "=== Final state ==="
kubectl get pods -n tailscale -o wide | grep ingress || echo "No ingress proxies"
echo ""

echo "========================================="
echo -e "${GREEN}Rollback Complete!${NC}"
echo "========================================="
echo ""
echo "Check your endpoints:"
echo "  curl https://grafana.tail57bf10.ts.net"
echo "  curl https://***.tail57bf10.ts.net"
echo "  curl https://***-1.tail57bf10.ts.net"
echo "  etc..."
echo ""
echo "If issues persist, check Tailscale operator logs:"
echo "  kubectl logs -n tailscale deployment/operator"
