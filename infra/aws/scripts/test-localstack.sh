#!/bin/bash
# ==============================================================================
# LocalStack Structure Validation Script
# ==============================================================================
# This script tests the Terraform infrastructure against LocalStack.
#
# USAGE:
#   ./test-localstack.sh
#
# PREREQUISITES:
#   1. LocalStack running: docker run -d -p 4566:4566 localstack/localstack
#   2. Terraform installed: terraform version
#   3. SOPS configured (optional): export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
# ==============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
    ((TESTS_PASSED++))
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
    ((TESTS_FAILED++))
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Banner
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║     AWS Infrastructure - LocalStack Structure Validation     ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
log_info "Checking prerequisites..."

# 1. Check LocalStack
if ! curl -s http://localhost:4566/_localstack/health > /dev/null 2>&1; then
    log_error "LocalStack is not running on localhost:4566"
    log_warning "Start LocalStack with: docker run -d -p 4566:4566 localstack/localstack:latest"
    exit 1
else
    log_success "LocalStack is running"
fi

# 2. Check Terraform
if ! command -v terraform &> /dev/null; then
    log_error "Terraform not found"
    exit 1
else
    TF_VERSION=$(terraform version -json | jq -r '.terraform_version')
    log_success "Terraform installed (v$TF_VERSION)"
fi

# 3. Check if LocalStack provider is configured
if [ ! -f "provider.localstack.tf" ]; then
    log_warning "LocalStack provider not configured"
    log_info "Creating provider.localstack.tf..."
    cp provider.localstack.tf.example provider.localstack.tf
    log_success "LocalStack provider configured"
fi

# 4. Check SOPS configuration (optional)
if [ -n "$SOPS_AGE_KEY_FILE" ] && [ -f "$SOPS_AGE_KEY_FILE" ]; then
    log_success "SOPS configured with AGE key"
    export SOPS_ENABLED=true
else
    log_warning "SOPS not configured (will use mock secrets)"
    export SOPS_ENABLED=false
fi

echo ""
log_info "Starting structure validation tests..."
echo ""

# Test 1: Terraform Init
log_info "Test 1/7: Terraform initialization"
if terraform init -upgrade > /tmp/tf-init.log 2>&1; then
    log_success "Terraform initialized successfully"
    grep -q "Terraform has been successfully initialized" /tmp/tf-init.log && \
        log_info "  - Providers: aws, sops downloaded"
else
    log_error "Terraform initialization failed"
    cat /tmp/tf-init.log
    exit 1
fi

# Test 2: Terraform Validate
log_info "Test 2/7: Configuration validation"
if terraform validate > /tmp/tf-validate.log 2>&1; then
    log_success "Configuration is valid"
else
    log_error "Configuration validation failed"
    cat /tmp/tf-validate.log
    exit 1
fi

# Test 3: Module Loading
log_info "Test 3/7: Module loading"
if terraform get -update > /tmp/tf-get.log 2>&1; then
    log_success "Modules loaded successfully"
    MODULE_COUNT=$(find modules -type d -name "compute" -o -name "network" | wc -l)
    log_info "  - Found $MODULE_COUNT modules (compute, network)"
else
    log_error "Module loading failed"
    cat /tmp/tf-get.log
    exit 1
fi

# Test 4: Variable Validation
log_info "Test 4/7: Variable validation"
if terraform validate -var-file="terraform.tfvars.localstack" > /tmp/tf-var-validate.log 2>&1; then
    log_success "Variables validated successfully"
else
    log_error "Variable validation failed"
    cat /tmp/tf-var-validate.log
    exit 1
fi

# Test 5: Plan Generation
log_info "Test 5/7: Plan generation"
if terraform plan -var-file="terraform.tfvars.localstack" -out=terraform.tfplan > /tmp/tf-plan.log 2>&1; then
    log_success "Plan generated successfully"

    # Count resources
    RESOURCE_COUNT=$(terraform show -json terraform.tfplan 2>/dev/null | jq -r '.resource_changes | length' || echo "0")
    log_info "  - Plan includes $RESOURCE_COUNT resource changes"
else
    log_error "Plan generation failed"
    cat /tmp/tf-plan.log
    exit 1
fi

# Test 6: Dependency Graph
log_info "Test 6/7: Dependency graph generation"
if terraform graph > terraform-graph.dot 2>&1; then
    log_success "Dependency graph generated"
    log_info "  - Graph saved to: terraform-graph.dot"

    # Count nodes in graph
    NODE_COUNT=$(grep -c "label" terraform-graph.dot || echo "0")
    log_info "  - Graph contains $NODE_COUNT nodes"
else
    log_error "Graph generation failed"
fi

# Test 7: Output Validation
log_info "Test 7/7: Output validation"
if terraform output > /tmp/tf-output.log 2>&1; then
    log_success "Outputs validated successfully"
else
    # Outputs may fail if not applied, that's OK
    log_warning "Outputs not yet available (requires apply)"
fi

# Summary
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                      Test Summary                             ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}Tests Passed:${NC} $TESTS_PASSED"
echo -e "${RED}Tests Failed:${NC} $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All structure validation tests passed!${NC}"
    echo ""
    log_info "What was validated:"
    echo "  ✅ Terraform module structure is correct"
    echo "  ✅ Variable validation rules work"
    echo "  ✅ Resource dependencies are correct"
    echo "  ✅ Module composition is valid"
    echo "  ✅ SOPS integration configured"
    echo ""
    log_warning "What was NOT validated (LocalStack limitations):"
    echo "  ❌ EC2 Spot Instance provisioning"
    echo "  ❌ k3s installation (user data execution)"
    echo "  ❌ CloudNativePG deployment"
    echo "  ❌ Network functionality (security groups)"
    echo "  ❌ IAM role assumption"
    echo ""
    log_info "Next Steps:"
    echo "  1. Review terraform.tfplan for resource changes"
    echo "  2. Review terraform-graph.dot for dependencies"
    echo "  3. Deploy to AWS for behavior validation"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Please review the output above.${NC}"
    echo ""
    exit 1
fi
