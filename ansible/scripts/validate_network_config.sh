#!/bin/bash
# Network Configuration Validation Script
# Validates the new network topology settings before deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================="
echo "Network Configuration Validation"
echo "================================================="
echo ""

# Function to print test results
print_result() {
    if [ "$1" -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $2"
    else
        echo -e "${RED}✗${NC} $2"
        return 1
    fi
}

ERRORS=0

# Test 1: Check if inventory file exists and has correct IPs
echo "→ Validating inventory file..."
if grep -q "ansible_host: 192.168.8.11" "$ANSIBLE_ROOT/inventory/production.yml" && \
   grep -q "ansible_host: 192.168.8.12" "$ANSIBLE_ROOT/inventory/production.yml" && \
   grep -q "ansible_host: 192.168.8.120" "$ANSIBLE_ROOT/inventory/production.yml" && \
   grep -q "ansible_host: 192.168.8.1" "$ANSIBLE_ROOT/inventory/production.yml"; then
    print_result 0 "All hosts have correct IP addresses"
else
    print_result 1 "Missing or incorrect IP addresses in inventory"
    ERRORS=$((ERRORS + 1))
fi

# Test 2: Check if group_vars has network CIDRs
echo "→ Validating global variables..."
if grep -q 'network_cidr: "192.168.8.0/24"' "$ANSIBLE_ROOT/group_vars/all.yml" && \
   grep -q 'guest_network_cidr: "192.168.9.0/24"' "$ANSIBLE_ROOT/group_vars/all.yml" && \
   grep -q 'gateway_ip: "192.168.8.1"' "$ANSIBLE_ROOT/group_vars/all.yml"; then
    print_result 0 "Network topology variables defined correctly"
else
    print_result 1 "Missing or incorrect network topology variables"
    ERRORS=$((ERRORS + 1))
fi

# Test 3: Check if gatekeeper role has Zero Trust rule
echo "→ Validating gatekeeper role..."
if grep -q "block_guest_to_admin" "$ANSIBLE_ROOT/roles/gatekeeper/tasks/main.yml" && \
   grep -q "guest_network_cidr" "$ANSIBLE_ROOT/roles/gatekeeper/tasks/main.yml"; then
    print_result 0 "Zero Trust isolation rule present"
else
    print_result 1 "Zero Trust isolation rule missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 4: Check if WAN DHCP configuration exists
echo "→ Validating WAN DHCP configuration..."
if grep -q "Configure WAN interface for DHCP" "$ANSIBLE_ROOT/roles/gatekeeper/tasks/main.yml" && \
   grep -q "network.wan.proto='dhcp'" "$ANSIBLE_ROOT/roles/gatekeeper/tasks/main.yml"; then
    print_result 0 "WAN DHCP configuration present"
else
    print_result 1 "WAN DHCP configuration missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 5: Verify router playbook exists
echo "→ Validating router playbook..."
if [ -f "$ANSIBLE_ROOT/playbooks/configure_router.yml" ]; then
    print_result 0 "Router playbook exists"
else
    print_result 1 "Router playbook missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 6: Check Ansible syntax (if ansible is available)
if command -v ansible-playbook &> /dev/null; then
    echo "→ Checking Ansible syntax..."
    if ansible-playbook --syntax-check "$ANSIBLE_ROOT/playbooks/configure_router.yml" &> /dev/null; then
        print_result 0 "Ansible playbook syntax valid"
    else
        print_result 1 "Ansible playbook has syntax errors"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${YELLOW}⚠${NC} Ansible not installed, skipping syntax check"
fi

# Summary
echo ""
echo "================================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}All validation checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Test with dry-run:"
    echo "     ansible-playbook -i inventory/production.yml playbooks/configure_router.yml --check"
    echo ""
    echo "  2. Apply configuration:"
    echo "     ansible-playbook -i inventory/production.yml playbooks/configure_router.yml"
    echo ""
    exit 0
else
    echo -e "${RED}Validation failed with $ERRORS error(s)${NC}"
    echo "Please fix the issues above before proceeding."
    echo ""
    exit 1
fi
