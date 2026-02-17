#!/bin/bash
# *** GitOps Bootstrap Verification Script
# Tests connectivity, API authentication, and category configuration

set -e

NAMESPACE="media"
QB_SERVICE="***:8080"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "*** Integration Verification"
echo "=========================================="
echo ""

# Function: Print status
status() {
    local result=$1
    local message=$2
    if [ "$result" = "success" ]; then
        echo -e "${GREEN}✓${NC} ${message}"
    elif [ "$result" = "warning" ]; then
        echo -e "${YELLOW}⚠${NC} ${message}"
    else
        echo -e "${RED}✗${NC} ${message}"
    fi
}

# 1. Check *** pod status
echo "1. Checking *** pod status..."
if kubectl get pods -n $NAMESPACE -l app=*** --field-selector=status.phase=Running | grep -q ***; then
    POD_NAME=$(kubectl get pods -n $NAMESPACE -l app=*** -o jsonpath='{.items[0].metadata.name}')
    status "success" "Pod is running: $POD_NAME"
else
    status "error" "*** pod is not running"
    exit 1
fi

# 2. Check VPN connection
echo ""
echo "2. Verifying VPN connection..."
PUBLIC_IP=$(kubectl exec -n $NAMESPACE $POD_NAME -c *** -- wget -qO- http://localhost:8000/v1/publicip/ip 2>/dev/null | grep -o '"public_ip":"[^"]*"' | cut -d'"' -f4)
if [ -n "$PUBLIC_IP" ]; then
    status "success" "VPN active - Public IP: $PUBLIC_IP"
else
    status "warning" "Could not verify VPN public IP"
fi

# 3. Test DNS resolution from ***
echo ""
echo "3. Testing DNS resolution from ***..."
if kubectl exec -n $NAMESPACE deploy/*** -- nslookup *** >/dev/null 2>&1; then
    RESOLVED_IP=$(kubectl exec -n $NAMESPACE deploy/*** -- nslookup *** 2>/dev/null | grep -A1 "Name:" | tail -1 | awk '{print $2}')
    status "success" "DNS resolution: *** → $RESOLVED_IP"
else
    status "error" "DNS resolution failed from ***"
fi

# 4. Test DNS resolution from ***
echo ""
echo "4. Testing DNS resolution from ***..."
if kubectl exec -n $NAMESPACE deploy/*** -- nslookup *** >/dev/null 2>&1; then
    RESOLVED_IP=$(kubectl exec -n $NAMESPACE deploy/*** -- nslookup *** 2>/dev/null | grep -A1 "Name:" | tail -1 | awk '{print $2}')
    status "success" "DNS resolution: *** → $RESOLVED_IP"
else
    status "error" "DNS resolution failed from ***"
fi

# 5. Test HTTP connectivity from ***
echo ""
echo "5. Testing HTTP connectivity from ***..."
if kubectl exec -n $NAMESPACE deploy/*** -- wget --spider --timeout=5 http://$QB_SERVICE >/dev/null 2>&1; then
    status "success" "HTTP connectivity from ***"
else
    status "error" "HTTP connectivity failed from ***"
fi

# 6. Test HTTP connectivity from ***
echo ""
echo "6. Testing HTTP connectivity from ***..."
if kubectl exec -n $NAMESPACE deploy/*** -- wget --spider --timeout=5 http://$QB_SERVICE >/dev/null 2>&1; then
    status "success" "HTTP connectivity from ***"
else
    status "error" "HTTP connectivity failed from ***"
fi

# 7. Check bootstrap Job status
echo ""
echo "7. Checking category bootstrap Job..."
if kubectl get job ***-category-bootstrap -n $NAMESPACE >/dev/null 2>&1; then
    JOB_STATUS=$(kubectl get job ***-category-bootstrap -n $NAMESPACE -o jsonpath='{.status.conditions[0].type}')
    if [ "$JOB_STATUS" = "Complete" ]; then
        status "success" "Bootstrap Job completed successfully"
    else
        status "warning" "Bootstrap Job status: $JOB_STATUS"
    fi
else
    status "warning" "Bootstrap Job not found (may have been cleaned up)"
fi

# 8. Verify categories exist (requires credentials)
echo ""
echo "8. Verifying *** categories..."
echo "   (Requires ***-secret to be configured)"

# Get credentials from secret
QB_USER=$(kubectl get secret ***-secret -n $NAMESPACE -o jsonpath='{.data.username}' 2>/dev/null | base64 -d)
QB_PASS=$(kubectl get secret ***-secret -n $NAMESPACE -o jsonpath='{.data.password}' 2>/dev/null | base64 -d)

if [ -n "$QB_USER" ] && [ -n "$QB_PASS" ]; then
    CATEGORIES=$(kubectl exec -n $NAMESPACE deploy/*** -- sh -c "
        curl -s -c /tmp/cookies.txt -d 'username=$QB_USER&password=$QB_PASS' http://$QB_SERVICE/api/v2/auth/login >/dev/null 2>&1
        curl -s -b /tmp/cookies.txt http://$QB_SERVICE/api/v2/torrents/categories
    " 2>/dev/null)

    if echo "$CATEGORIES" | grep -q '"movies"'; then
        status "success" "Category 'movies' exists"
    else
        status "error" "Category 'movies' not found"
    fi

    if echo "$CATEGORIES" | grep -q '"tv-***"'; then
        status "success" "Category 'tv-***' exists"
    else
        status "error" "Category 'tv-***' not found"
    fi
else
    status "warning" "Could not retrieve credentials from secret"
fi

# 9. Check UMASK configuration
echo ""
echo "9. Verifying UMASK configuration..."
UMASK_VALUE=$(kubectl exec -n $NAMESPACE $POD_NAME -c *** -- sh -c 'umask' 2>/dev/null)
if [ "$UMASK_VALUE" = "0002" ]; then
    status "success" "UMASK is correctly set to 0002 (group-writable)"
else
    status "warning" "UMASK is $UMASK_VALUE (expected 0002)"
fi

# 10. Check shared storage mount
echo ""
echo "10. Verifying shared storage mount..."
if kubectl exec -n $NAMESPACE $POD_NAME -c *** -- ls -ld /data >/dev/null 2>&1; then
    MOUNT_INFO=$(kubectl exec -n $NAMESPACE $POD_NAME -c *** -- ls -ld /data 2>/dev/null)
    status "success" "Shared PVC mounted at /data"
    echo "    $MOUNT_INFO"
else
    status "error" "Shared PVC not mounted"
fi

# Summary
echo ""
echo "=========================================="
echo "Verification Complete"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "  1. Configure Download Client in ***:"
echo "     Settings → Download Clients → Add ***"
echo "     Host: ***, Port: 8080"
echo "     Category: movies"
echo ""
echo "  2. Configure Download Client in ***:"
echo "     Settings → Download Clients → Add ***"
echo "     Host: ***, Port: 8080"
echo "     Category: tv-***"
echo ""
echo "  3. Test download automation:"
echo "     Add a movie/show and monitor the download flow"
echo ""
