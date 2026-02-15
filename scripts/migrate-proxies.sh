#!/bin/bash
# RPi 4 Proxy Optimization - Migrate proxies to reduce load (IMPROVED VERSION)
# Run this from your workstation with kubectl access

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================="
echo "RPi 4 Tailscale Proxy Migration"
echo "IMPROVED VERSION - With Safety Checks"
echo "========================================="
echo ""
echo "This will:"
echo "1. Document current state"
echo "2. Cordon RPi 4 (prevent new pods from scheduling there)"
echo "3. Delete 6 proxies that should run elsewhere (only if on RPi 4)"
echo "4. Fix 2 proxies on wrong nodes (delete before uncordon)"
echo "5. Wait for all pods to be Ready"
echo "6. Uncordon RPi 4"
echo "7. Verify final distribution"
echo ""
echo -e "${YELLOW}SAFETY FEATURES:${NC}"
echo "- Only deletes pods actually running on RPi 4"
echo "- Verifies pods are Ready before uncordoning"
echo "- Shows rollback commands if needed"
echo ""

read -p "Proceed? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "=== Step 1: Documenting current state ==="
echo "Current proxy distribution:"
kubectl get pods -n tailscale -o wide | grep ingress || echo "No ingress proxies found"
echo ""

# Count proxies on each node
echo "Proxy count by node:"
kubectl get pods -n tailscale -o wide | grep ingress | awk '{print $7}' | sort | uniq -c || echo "N/A"
echo ""

echo "=== Step 2: Cordoning RPi 4 ==="
kubectl cordon rasp-pi-04
echo -e "${GREEN}✓ RPi 4 cordoned${NC} (no new pods can schedule there)"
echo ""

# Store cordon status for rollback
echo -e "${YELLOW}Rollback command if needed:${NC} kubectl uncordon rasp-pi-04"
echo ""

echo "=== Step 3: Finding proxies to migrate OFF RPi 4 ==="
echo "Looking for proxies on RPi 4 that should be elsewhere..."

# IMPROVED: Only select pods that are actually on RPi 4
PROXIES_TO_DELETE=$(kubectl get pods -n tailscale -o wide | grep "rasp-pi-04" | grep -E "(adguard|golink|grafana|loki|prometheus|searxng)-ingress" | awk '{print $1}' || true)

if [ -n "$PROXIES_TO_DELETE" ]; then
    echo -e "Found proxies on RPi 4 to migrate:"
    echo "$PROXIES_TO_DELETE"
    echo ""
    echo "Deleting these pods (they will recreate on correct nodes)..."

    # Delete one by one with error handling
    for pod in $PROXIES_TO_DELETE; do
        echo -n "  Deleting $pod... "
        if kubectl delete -n tailscale pod $pod --grace-period=30 --ignore-not-found=true; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${YELLOW}⚠ Already gone or error${NC}"
        fi
    done
    echo -e "${GREEN}✓ Proxies deleted${NC}"
else
    echo -e "${YELLOW}No matching proxies found on RPi 4${NC}"
fi

echo ""
echo "=== Step 4: Fixing proxies on wrong nodes (Step 6 in original) ==="
echo "Looking for ***/*** proxies NOT on RPi 4..."

# Find ***/*** proxies NOT on RPi 4
WRONG_PROXIES=$(kubectl get pods -n tailscale -o wide | grep -v "rasp-pi-04" | grep -E "(***|***)-ingress" | awk '{print $1}' || true)

if [ -n "$WRONG_PROXIES" ]; then
    echo "Found proxies on wrong nodes:"
    echo "$WRONG_PROXIES"
    echo ""
    echo "Deleting (they will recreate on RPi 4 with apps)..."

    for pod in $WRONG_PROXIES; do
        echo -n "  Deleting $pod... "
        if kubectl delete -n tailscale pod $pod --grace-period=30 --ignore-not-found=true; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${YELLOW}⚠ Already gone${NC}"
        fi
    done
    echo -e "${GREEN}✓ Wrong-node proxies deleted${NC}"
else
    echo -e "${GREEN}No wrong-node proxies found (good!)${NC}"
fi

echo ""
echo "=== Step 5: Waiting for all Tailscale pods to be Ready ==="
echo "This may take up to 2 minutes..."

# IMPROVED: Wait for all Tailscale pods to be Ready before uncordoning
if kubectl wait --for=condition=Ready pods -n tailscale -l tailscale.com/proxy-class=default --timeout=120s; then
    echo -e "${GREEN}✓ All Tailscale pods are Ready${NC}"
else
    echo -e "${YELLOW}⚠ Timeout waiting for pods. Check status manually.${NC}"
    echo "Continuing anyway..."
fi

echo ""
echo "Current proxy distribution:"
kubectl get pods -n tailscale -o wide | grep ingress || echo "No ingress proxies found"
echo ""

echo "=== Step 6: Uncordoning RPi 4 ==="
kubectl uncordon rasp-pi-04
echo -e "${GREEN}✓ RPi 4 uncordoned${NC}"
echo ""

echo "=== Step 7: Final verification ==="
echo "Waiting 10 seconds for any final rescheduling..."
sleep 10
echo ""

echo "Final proxy distribution:"
kubectl get pods -n tailscale -o wide | grep ingress || echo "No ingress proxies found"
echo ""

echo "Proxy count by node (should be ~5 on rasp-pi-04):"
kubectl get pods -n tailscale -o wide | grep ingress | awk '{print $7}' | sort | uniq -c || echo "N/A"
echo ""

echo "========================================="
echo -e "${GREEN}Migration Complete!${NC}"
echo "========================================="
echo ""
echo "Expected results:"
echo "- RPi 4 should have ~5 proxies (down from 9)"
echo "- AWS nodes should have 2-3 proxies each"
echo "- RPi 3 should have ~3 proxies"
echo ""
echo -e "${YELLOW}Verification commands:${NC}"
echo "  kubectl get pods -n tailscale -o wide"
echo "  kubectl top nodes"
echo ""
echo "Next steps:"
echo "1. Verify all endpoints are accessible:"
echo "   - curl https://grafana.tail57bf10.ts.net"
echo "   - curl https://***.tail57bf10.ts.net"
echo "   - etc..."
echo ""
echo "2. Run swap optimization on RPi 4:"
echo "   ssh ubuntu@rasp-pi-04.tail57bf10.ts.net"
echo "   sudo bash /var/mnt/nvme/repos/repos/homelab/scripts/optimize-rpi4-swap.sh"
echo ""
