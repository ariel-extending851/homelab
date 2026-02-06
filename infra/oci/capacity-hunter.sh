#!/usr/bin/env bash
#
# OCI ARM Capacity Hunter
# Automatically retries terraform apply until ARM instances are provisioned
#
# Usage:
#   ./capacity-hunter.sh [RETRY_INTERVAL_SECONDS]
#
# Default retry interval: 300 seconds (5 minutes)
#

set -euo pipefail

RETRY_INTERVAL="${1:-300}"
MAX_RETRIES="${2:-288}" # 24 hours at 5-minute intervals
ATTEMPT=0

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║           OCI ARM Always Free - Capacity Hunter                   ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Configuration:"
echo "  Retry Interval: ${RETRY_INTERVAL} seconds"
echo "  Max Retries:    ${MAX_RETRIES}"
echo "  Target:         1x VM.Standard.A1.Flex (ARM64)"
echo "  Region:         sa-saopaulo-1"
echo ""

while [ $ATTEMPT -lt $MAX_RETRIES ]; do
  ATTEMPT=$((ATTEMPT + 1))
  TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "🔄 Attempt #${ATTEMPT}/${MAX_RETRIES} - ${TIMESTAMP}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # Run terraform apply and capture output
  if terraform apply -auto-approve -no-color 2>&1 | tee /tmp/terraform-apply-$ATTEMPT.log; then
  # Check if at least 1 ARM instance was successfully created
  if terraform state list | grep -q "module.k3s_nodes.oci_core_instance.k3s_node\[0\]"; then

      echo ""
      echo "╔════════════════════════════════════════════════════════════════════╗"
      echo "║  ✅ SUCCESS! ARM instance provisioned successfully!              ║"
      echo "╚════════════════════════════════════════════════════════════════════╝"
      echo ""
      echo "Instance Details:"
      terraform show -no-color | grep -A 5 "hl-k3s-node"

      echo ""
      echo "Next Steps:"
      echo "  1. Verify instances: oci compute instance list --compartment-id <COMPARTMENT_ID>"
      echo "  2. SSH to instances: ssh ubuntu@<PUBLIC_IP>"
      echo "  3. Verify architecture: uname -m (should output: aarch64)"
      echo "  4. Redeploy K3s cluster via Ansible"

      exit 0
    fi
  fi

  # Check if capacity error occurred
  if grep -q "Out of host capacity" /tmp/terraform-apply-$ATTEMPT.log; then
    echo ""
    echo "⚠️  Capacity unavailable - Retrying in ${RETRY_INTERVAL} seconds..."
    echo "    (Attempt ${ATTEMPT}/${MAX_RETRIES})"
    echo ""
  else
    echo ""
    echo "❌ Unexpected error - Check log: /tmp/terraform-apply-$ATTEMPT.log"
    echo "    Retrying in ${RETRY_INTERVAL} seconds..."
    echo ""
  fi

  # Wait before next attempt (unless this is the last attempt)
  if [ $ATTEMPT -lt $MAX_RETRIES ]; then
    sleep "$RETRY_INTERVAL"
  fi
done

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  ❌ FAILED: Max retries reached without success                   ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Suggestions:"
echo "  1. Try again during off-peak hours (late night / early morning)"
echo "  2. Consider using a different region (e.g., sa-vinhedo-1)"
echo "  3. Check OCI console for capacity status"
echo "  4. Contact OCI support if issue persists"
echo ""

exit 1
