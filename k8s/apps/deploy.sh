#!/bin/bash
# Automated deployment script for modular GitOps apps
# Usage: ./deploy.sh [--skip-secrets]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SKIP_SECRETS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-secrets)
      SKIP_SECRETS=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo -e "${GREEN}=== Modular GitOps Deployment ===${NC}"
echo ""

# Function to wait for deployment
wait_for_deployment() {
  local namespace=$1
  local deployment=$2
  local timeout=${3:-300}
  
  echo -e "${YELLOW}Waiting for $deployment in $namespace to be ready...${NC}"
  kubectl wait --for=condition=available deployment/$deployment -n $namespace --timeout=${timeout}s
  echo -e "${GREEN}✓ $deployment is ready${NC}"
}

# Function to wait for daemonset
wait_for_daemonset() {
  local namespace=$1
  local daemonset=$2
  
  echo -e "${YELLOW}Waiting for $daemonset in $namespace to be ready...${NC}"
  kubectl rollout status daemonset/$daemonset -n $namespace --timeout=300s
  echo -e "${GREEN}✓ $daemonset is ready${NC}"
}

# Check for Tailscale auth keys if not skipping
if [ "$SKIP_SECRETS" = false ]; then
  echo -e "${YELLOW}Checking Tailscale auth secrets...${NC}"
  
  MISSING_SECRETS=()
  
  for ns in grafana prometheus loki adguard; do
    if ! kubectl get secret tailscale-auth -n $ns &>/dev/null; then
      MISSING_SECRETS+=("$ns")
    fi
  done
  
  if [ ${#MISSING_SECRETS[@]} -gt 0 ]; then
    echo -e "${RED}ERROR: Missing Tailscale auth secrets in namespaces: ${MISSING_SECRETS[*]}${NC}"
    echo ""
    echo "Create secrets using:"
    for ns in "${MISSING_SECRETS[@]}"; do
      echo "  kubectl create secret generic tailscale-auth --from-literal=authkey=tskey-auth-XXX -n $ns"
    done
    echo ""
    echo "Or run with --skip-secrets to deploy without checking (secrets must exist in YAML files)"
    exit 1
  fi
  
  echo -e "${GREEN}✓ All Tailscale secrets found${NC}"
  echo ""
fi

# Step 1: Foundation Services
echo -e "${GREEN}=== Step 1: Deploying Foundation Services ===${NC}"
echo ""

echo "Deploying kube-state-metrics..."
kubectl apply -k k8s/apps/kube-state-metrics/
wait_for_deployment kube-state-metrics kube-state-metrics 120

echo ""
echo "Deploying node-exporter..."
kubectl apply -k k8s/apps/node-exporter/
wait_for_daemonset node-exporter node-exporter

echo ""
echo "Deploying blackbox-exporter..."
kubectl apply -k k8s/apps/blackbox/
wait_for_deployment blackbox blackbox-exporter 120

echo ""
echo -e "${GREEN}✓ Foundation services deployed${NC}"
echo ""

# Step 2: Log Aggregation
echo -e "${GREEN}=== Step 2: Deploying Log Aggregation ===${NC}"
echo ""

echo "Deploying Loki..."
kubectl apply -k k8s/apps/loki/
wait_for_deployment loki loki 300

echo ""
echo -e "${GREEN}✓ Loki deployed${NC}"
echo ""

# Step 3: OTEL Collector
echo -e "${GREEN}=== Step 3: Deploying OTEL Collector ===${NC}"
echo ""

echo "Deploying OTEL Collector..."
kubectl apply -k k8s/apps/otel-collector/
wait_for_daemonset otel-collector otel-collector

echo ""
echo -e "${GREEN}✓ OTEL Collector deployed${NC}"
echo ""

# Step 4: Prometheus
echo -e "${GREEN}=== Step 4: Deploying Prometheus ===${NC}"
echo ""

echo "Deploying Prometheus..."
kubectl apply -k k8s/apps/prometheus/
wait_for_deployment prometheus prometheus 300

echo ""
echo -e "${GREEN}✓ Prometheus deployed${NC}"
echo ""

# Step 5: Grafana
echo -e "${GREEN}=== Step 5: Deploying Grafana ===${NC}"
echo ""

echo "Deploying Grafana..."
kubectl apply -k k8s/apps/grafana/
wait_for_deployment grafana grafana 300

echo ""
echo -e "${GREEN}✓ Grafana deployed${NC}"
echo ""

# Step 6: AdGuard
echo -e "${GREEN}=== Step 6: Deploying AdGuard ===${NC}"
echo ""

echo "Deploying AdGuard Home..."
kubectl apply -k k8s/apps/adguard/
wait_for_deployment adguard adguardhome 180

echo ""
echo -e "${GREEN}✓ AdGuard deployed${NC}"
echo ""

# Summary
echo ""
echo -e "${GREEN}==================================================================${NC}"
echo -e "${GREEN}           🎉 Deployment Complete! 🎉${NC}"
echo -e "${GREEN}==================================================================${NC}"
echo ""
echo "All services have been deployed successfully!"
echo ""
echo "Next steps:"
echo "1. Check Tailscale status: tailscale status"
echo "2. Access services via HTTPS:"
echo "   - Grafana: https://grafana.<your-tailnet>.ts.net"
echo "   - Prometheus: https://prometheus.<your-tailnet>.ts.net"
echo "   - Loki: https://loki.<your-tailnet>.ts.net"
echo "   - AdGuard: https://adguard.<your-tailnet>.ts.net"
echo ""
echo "3. Update Grafana datasources:"
echo "   - Prometheus: http://prometheus.prometheus.svc.cluster.local:9090"
echo "   - Loki: http://loki.loki.svc.cluster.local:3100"
echo ""
echo "For detailed troubleshooting, see k8s/apps/DEPLOYMENT.md"
echo ""
