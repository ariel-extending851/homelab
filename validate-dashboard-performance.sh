#!/bin/bash
set -euo pipefail

###############################################################################
# Grafana Dashboard Performance Validation Script
# Purpose: Validate PR #27 performance improvements after merge
# Expected Results:
#   - Dashboard load time: < 3 seconds (was 11.7s)
#   - Loki query time: < 500ms (was 2.5s)
#   - CPU throttling: < 0.1% (was 0.38%)
#   - All 20 panels display data (no "No Data" errors)
###############################################################################

GRAFANA_NAMESPACE="grafana"
LOKI_NAMESPACE="loki"
EXPECTED_PANELS=20
EXPECTED_CONFIGMAPS=3

echo "============================================================"
echo "Grafana Dashboard Performance Validation"
echo "PR #27: perf(monitoring): Optimize Grafana/Loki performance"
echo "============================================================"
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

###############################################################################
# Test 1: Verify Grafana Pod Status
###############################################################################
echo "📊 Test 1: Grafana Pod Status"
echo "------------------------------------------------------------"

GRAFANA_POD=$(kubectl get pod -n $GRAFANA_NAMESPACE -l app=grafana -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [ -z "$GRAFANA_POD" ]; then
    echo -e "${RED}❌ FAIL${NC}: Grafana pod not found in namespace '$GRAFANA_NAMESPACE'"
    exit 1
fi

POD_STATUS=$(kubectl get pod -n $GRAFANA_NAMESPACE $GRAFANA_POD -o jsonpath='{.status.phase}')
POD_READY=$(kubectl get pod -n $GRAFANA_NAMESPACE $GRAFANA_POD -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')

if [ "$POD_STATUS" == "Running" ] && [ "$POD_READY" == "True" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Grafana pod '$GRAFANA_POD' is Running and Ready"
else
    echo -e "${RED}❌ FAIL${NC}: Grafana pod status: $POD_STATUS, Ready: $POD_READY"
    kubectl describe pod -n $GRAFANA_NAMESPACE $GRAFANA_POD
    exit 1
fi

# Check CPU limit
CPU_LIMIT=$(kubectl get pod -n $GRAFANA_NAMESPACE $GRAFANA_POD -o jsonpath='{.spec.containers[0].resources.limits.cpu}')
echo "   CPU Limit: $CPU_LIMIT (expected: 1000m or 1)"

if [ "$CPU_LIMIT" == "1000m" ] || [ "$CPU_LIMIT" == "1" ]; then
    echo -e "${GREEN}✅ PASS${NC}: CPU limit correctly set to 1000m"
else
    echo -e "${YELLOW}⚠️  WARN${NC}: CPU limit is '$CPU_LIMIT', expected '1000m'"
fi

echo ""

###############################################################################
# Test 2: Verify Dashboard ConfigMaps
###############################################################################
echo "📁 Test 2: Dashboard ConfigMaps"
echo "------------------------------------------------------------"

CONFIGMAPS=$(kubectl get configmap -n $GRAFANA_NAMESPACE --no-headers 2>/dev/null | wc -l)

if [ "$CONFIGMAPS" -ge "$EXPECTED_CONFIGMAPS" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Found $CONFIGMAPS ConfigMaps (expected >= $EXPECTED_CONFIGMAPS)"
else
    echo -e "${RED}❌ FAIL${NC}: Found $CONFIGMAPS ConfigMaps (expected >= $EXPECTED_CONFIGMAPS)"
fi

# Check specific ConfigMaps
declare -a REQUIRED_CMS=(
    "grafana-dashboard-provider"
    "grafana-dashboard-homelab-k3s-overview"
    "grafana-datasources"
)

for cm in "${REQUIRED_CMS[@]}"; do
    if kubectl get configmap -n $GRAFANA_NAMESPACE $cm &>/dev/null; then
        SIZE=$(kubectl get configmap -n $GRAFANA_NAMESPACE $cm -o jsonpath='{.data}' | wc -c)
        echo -e "${GREEN}✅ PASS${NC}: ConfigMap '$cm' exists ($SIZE bytes)"
    else
        echo -e "${RED}❌ FAIL${NC}: ConfigMap '$cm' not found"
    fi
done

echo ""

###############################################################################
# Test 3: Verify Dashboard Files Mounted
###############################################################################
echo "📄 Test 3: Dashboard Files Mounted in Pod"
echo "------------------------------------------------------------"

# Check dashboard provisioner config
if kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- cat /etc/grafana/provisioning/dashboards/dashboards.yaml &>/dev/null; then
    PROVIDER_SIZE=$(kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- stat -c%s /etc/grafana/provisioning/dashboards/dashboards.yaml 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ PASS${NC}: Dashboard provider config mounted ($PROVIDER_SIZE bytes)"
else
    echo -e "${RED}❌ FAIL${NC}: Dashboard provider config not found at /etc/grafana/provisioning/dashboards/dashboards.yaml"
fi

# Check dashboard JSON
if kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- cat /etc/grafana/provisioning/dashboards/homelab-k3s-overview.json &>/dev/null; then
    DASHBOARD_SIZE=$(kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- stat -c%s /etc/grafana/provisioning/dashboards/homelab-k3s-overview.json 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ PASS${NC}: Dashboard JSON mounted ($DASHBOARD_SIZE bytes, expected ~50KB)"
    
    # Validate panel count
    PANEL_COUNT=$(kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- cat /etc/grafana/provisioning/dashboards/homelab-k3s-overview.json 2>/dev/null | grep -o '"type":"[^"]*"' | wc -l)
    
    if [ "$PANEL_COUNT" -ge "$EXPECTED_PANELS" ]; then
        echo -e "${GREEN}✅ PASS${NC}: Dashboard contains $PANEL_COUNT panels (expected >= $EXPECTED_PANELS)"
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: Dashboard contains $PANEL_COUNT panels (expected >= $EXPECTED_PANELS)"
    fi
else
    echo -e "${RED}❌ FAIL${NC}: Dashboard JSON not found at /etc/grafana/provisioning/dashboards/homelab-k3s-overview.json"
fi

echo ""

###############################################################################
# Test 4: Verify Loki Configuration
###############################################################################
echo "🔍 Test 4: Loki Configuration Optimization"
echo "------------------------------------------------------------"

LOKI_CM="loki"

if kubectl get configmap -n $LOKI_NAMESPACE $LOKI_CM &>/dev/null; then
    echo -e "${GREEN}✅ PASS${NC}: Loki ConfigMap '$LOKI_CM' exists"
    
    # Check query parallelism
    MAX_PARALLELISM=$(kubectl get configmap -n $LOKI_NAMESPACE $LOKI_CM -o jsonpath='{.data.config\.yaml}' 2>/dev/null | grep 'max_query_parallelism' | grep -o '[0-9]*' || echo "0")
    
    if [ "$MAX_PARALLELISM" -ge 16 ]; then
        echo -e "${GREEN}✅ PASS${NC}: max_query_parallelism set to $MAX_PARALLELISM (expected >= 16)"
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: max_query_parallelism is $MAX_PARALLELISM (expected >= 16)"
    fi
    
    # Check result caching
    if kubectl get configmap -n $LOKI_NAMESPACE $LOKI_CM -o jsonpath='{.data.config\.yaml}' 2>/dev/null | grep -q 'cache_results: true'; then
        echo -e "${GREEN}✅ PASS${NC}: Loki result caching enabled"
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: Loki result caching not found in config"
    fi
else
    echo -e "${RED}❌ FAIL${NC}: Loki ConfigMap '$LOKI_CM' not found in namespace '$LOKI_NAMESPACE'"
fi

echo ""

###############################################################################
# Test 5: Check CPU Throttling
###############################################################################
echo "🚦 Test 5: CPU Throttling Analysis"
echo "------------------------------------------------------------"

# Get throttling stats
THROTTLED_PERIODS=$(kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- cat /sys/fs/cgroup/cpu.stat 2>/dev/null | grep 'nr_throttled' | awk '{print $2}' || echo "0")
TOTAL_PERIODS=$(kubectl exec -n $GRAFANA_NAMESPACE $GRAFANA_POD -- cat /sys/fs/cgroup/cpu.stat 2>/dev/null | grep 'nr_periods' | awk '{print $2}' || echo "1")

if [ "$TOTAL_PERIODS" -gt 0 ]; then
    THROTTLE_PERCENT=$(awk "BEGIN {printf \"%.2f\", ($THROTTLED_PERIODS / $TOTAL_PERIODS) * 100}")
    echo "   Throttled Periods: $THROTTLED_PERIODS"
    echo "   Total Periods: $TOTAL_PERIODS"
    echo "   Throttle Percentage: ${THROTTLE_PERCENT}%"
    
    if (( $(echo "$THROTTLE_PERCENT < 0.1" | bc -l) )); then
        echo -e "${GREEN}✅ PASS${NC}: CPU throttling < 0.1% (target achieved)"
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: CPU throttling is ${THROTTLE_PERCENT}% (expected < 0.1%)"
    fi
else
    echo -e "${YELLOW}⚠️  WARN${NC}: Unable to calculate throttling percentage"
fi

echo ""

###############################################################################
# Test 6: Check Grafana Logs for Errors
###############################################################################
echo "📋 Test 6: Grafana Error Log Analysis"
echo "------------------------------------------------------------"

# Check for HTTP 400 errors (query errors)
HTTP_400_COUNT=$(kubectl logs -n $GRAFANA_NAMESPACE $GRAFANA_POD --tail=1000 2>/dev/null | grep -c 'status=400' || echo "0")

if [ "$HTTP_400_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ PASS${NC}: No HTTP 400 errors in last 1000 log lines"
else
    echo -e "${RED}❌ FAIL${NC}: Found $HTTP_400_COUNT HTTP 400 errors in logs"
    echo "   Recent errors:"
    kubectl logs -n $GRAFANA_NAMESPACE $GRAFANA_POD --tail=1000 2>/dev/null | grep 'status=400' | tail -5
fi

# Check for panel errors
PANEL_ERROR_COUNT=$(kubectl logs -n $GRAFANA_NAMESPACE $GRAFANA_POD --tail=1000 2>/dev/null | grep -i 'panel.*error' | wc -l || echo "0")

if [ "$PANEL_ERROR_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ PASS${NC}: No panel errors in last 1000 log lines"
else
    echo -e "${YELLOW}⚠️  WARN${NC}: Found $PANEL_ERROR_COUNT panel-related errors in logs"
fi

echo ""

###############################################################################
# Test 7: ArgoCD Sync Status
###############################################################################
echo "🔄 Test 7: ArgoCD Sync Status"
echo "------------------------------------------------------------"

ARGOCD_APP="homelab-apps-root"
ARGOCD_NAMESPACE="argocd"

if kubectl get application -n $ARGOCD_NAMESPACE $ARGOCD_APP &>/dev/null; then
    SYNC_STATUS=$(kubectl get application -n $ARGOCD_NAMESPACE $ARGOCD_APP -o jsonpath='{.status.sync.status}')
    TARGET_REVISION=$(kubectl get application -n $ARGOCD_NAMESPACE $ARGOCD_APP -o jsonpath='{.spec.source.targetRevision}')
    CURRENT_REVISION=$(kubectl get application -n $ARGOCD_NAMESPACE $ARGOCD_APP -o jsonpath='{.status.sync.revision}' | cut -c1-7)
    
    echo "   Sync Status: $SYNC_STATUS"
    echo "   Target Revision: $TARGET_REVISION"
    echo "   Current Revision: $CURRENT_REVISION"
    
    if [ "$SYNC_STATUS" == "Synced" ]; then
        echo -e "${GREEN}✅ PASS${NC}: ArgoCD application is synced"
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: ArgoCD sync status is '$SYNC_STATUS' (expected 'Synced')"
    fi
    
    # Check if syncing from feature branch (should be reverted after PR merge)
    if [ "$TARGET_REVISION" == "fix/grafana-dashboard-provisioning" ]; then
        echo -e "${YELLOW}⚠️  ACTION REQUIRED${NC}: ArgoCD is syncing from feature branch!"
        echo "   After PR merge, run:"
        echo "   kubectl patch application $ARGOCD_APP -n $ARGOCD_NAMESPACE \\"
        echo "     --type=json -p='[{\"op\": \"replace\", \"path\": \"/spec/source/targetRevision\", \"value\": \"develop\"}]'"
    elif [ "$TARGET_REVISION" == "develop" ]; then
        echo -e "${GREEN}✅ PASS${NC}: ArgoCD correctly syncing from 'develop' branch"
    fi
else
    echo -e "${RED}❌ FAIL${NC}: ArgoCD application '$ARGOCD_APP' not found"
fi

echo ""

###############################################################################
# Summary & Manual Validation Steps
###############################################################################
echo "============================================================"
echo "Manual Validation Required"
echo "============================================================"
echo ""
echo "Please complete the following manual tests:"
echo ""
echo "1. 🌐 Access Grafana Dashboard:"
echo "   URL: https://grafana.tail57bf10.ts.net"
echo "   Dashboard: Browse → 'K3s Homelab and Hybrid Cloud Overview - Comprehensive'"
echo ""
echo "2. ⏱️  Measure Dashboard Load Time:"
echo "   - Open browser DevTools (F12)"
echo "   - Go to Network tab"
echo "   - Refresh dashboard"
echo "   - Check 'DOMContentLoaded' time in Network tab summary"
echo "   - ${GREEN}Expected: < 3 seconds${NC} (previous: 11.7s)"
echo ""
echo "3. 📊 Verify Panel Data:"
echo "   - All 20 panels should display data (no 'No Data' messages)"
echo "   - Check Network Analysis section (Row 2):"
echo "     ✓ Network I/O per Interface"
echo "     ✓ Network Errors and Drops"
echo "     ✓ Active Network Connections"
echo "     ✓ Pods per Namespace"
echo ""
echo "4. 🔍 Check Browser Console:"
echo "   - Open DevTools Console tab"
echo "   - Verify: ${GREEN}Zero errors${NC} (no red messages)"
echo ""
echo "5. 📈 Monitor Loki Query Performance (24-48 hours):"
echo "   - Navigate to Explore → Loki datasource"
echo "   - Run sample queries from dashboard"
echo "   - Check query execution time at bottom of results"
echo "   - ${GREEN}Expected: < 500ms${NC} (previous: 2.5s)"
echo ""
echo "Sample Loki query to test:"
echo "   {exporter=\"OTLP\", attributes_k8s_namespace_name=~\"grafana|prometheus|loki\"} | json"
echo ""
echo "============================================================"
echo "Validation Script Complete"
echo "============================================================"
