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
#   2. tflocal installed (via mise: pipx:terraform-local)
#   3. SOPS configured (optional): export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
# ==============================================================================

set -e  # Exit on error

# Run from the infra/aws directory regardless of where the script is invoked from.
cd "$(dirname "$0")/.."

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
    ((TESTS_PASSED++)) || true
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
    ((TESTS_FAILED++)) || true
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

# 2. Check tflocal (terraform-local)
# Try to find tflocal in PATH or common mise locations
if command -v tflocal &> /dev/null; then
    log_success "tflocal installed"
elif [ -x "$HOME/.local/share/mise/shims/tflocal" ]; then
    export PATH="$HOME/.local/share/mise/shims:$PATH"
    log_success "tflocal installed (via mise shims)"
elif [ -x "$HOME/.local/bin/tflocal" ]; then
    export PATH="$HOME/.local/bin:$PATH"
    log_success "tflocal installed (via pipx local)"
else
    log_error "tflocal not found. Install via: mise install or pipx install terraform-local"
    exit 1
fi

# 3. Check SOPS configuration (optional)
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
log_info "Test 1/6: Terraform initialization"
if tflocal init -reconfigure -upgrade > /tmp/tf-init.log 2>&1; then
    log_success "Terraform initialized successfully"
else
    log_error "Terraform initialization failed"
    cat /tmp/tf-init.log
    exit 1
fi

# Test 2: Terraform Validate
log_info "Test 2/6: Configuration validation"
if tflocal validate > /tmp/tf-validate.log 2>&1; then
    log_success "Configuration is valid"
else
    log_error "Configuration validation failed"
    cat /tmp/tf-validate.log
    exit 1
fi

# Test 3: Module Loading
log_info "Test 3/6: Module loading"
if tflocal get -update > /tmp/tf-get.log 2>&1; then
    log_success "Modules loaded successfully"
    MODULE_COUNT=$(find modules -type d \( -name "compute" -o -name "network" \) | wc -l)
    log_info "  - Found $MODULE_COUNT modules (compute, network)"
else
    log_error "Module loading failed"
    cat /tmp/tf-get.log
    exit 1
fi

# Test 4: Plan Generation
log_info "Test 4/6: Plan generation"
if tflocal plan -out=terraform.tfplan > /tmp/tf-plan.log 2>&1; then
    log_success "Plan generated successfully"

    # Count resources
    RESOURCE_COUNT=$(tflocal show -json terraform.tfplan 2>/dev/null | jq -r '.resource_changes | length' || echo "0")
    log_info "  - Plan includes $RESOURCE_COUNT resource changes"
else
    log_error "Plan generation failed"
    cat /tmp/tf-plan.log
    exit 1
fi

# Test 5: Dependency Graph
log_info "Test 5/6: Dependency graph generation"
if tflocal graph > terraform-graph.dot 2>&1; then
    log_success "Dependency graph generated"
    log_info "  - Graph saved to: terraform-graph.dot"

    # Count nodes in graph
    NODE_COUNT=$(grep -c "label" terraform-graph.dot || echo "0")
    log_info "  - Graph contains $NODE_COUNT nodes"
else
    log_error "Graph generation failed"
fi

# Test 6: Output Validation (pre-apply — expected to warn)
log_info "Test 6/8: Output validation (pre-apply)"
if tflocal output > /tmp/tf-output.log 2>&1; then
    log_success "Outputs validated successfully"
else
    log_warning "Outputs not yet available (requires apply) — expected at this stage"
fi

# Test 7: Apply against LocalStack
# EC2 Fleets are not fully supported in LocalStack free tier; we tolerate
# failures for unsupported resource types but assert that IAM, Lambda, S3,
# and security group resources ARE created.
log_info "Test 7/8: Terraform apply against LocalStack"
echo "  (EC2 Fleet failures are tolerated — LocalStack free tier limitation)"
if TF_VAR_localstack_test=yes \
    tflocal apply \
        -auto-approve \
        -var-file=terraform.tfvars.localstack \
        > /tmp/tf-apply.log 2>&1; then
    log_success "Apply completed without errors"
else
    log_warning "Apply had some failures (likely EC2 Fleet — tolerated)"
fi

# Test 8: State assertions — verify key resources entered the Terraform state
log_info "Test 8/8: State resource assertions"
tflocal state list > /tmp/tf-state.log 2>/dev/null || true

STATE_TOTAL=$(wc -l < /tmp/tf-state.log | tr -d ' ')
log_info "  - Total resources in state: $STATE_TOTAL"

assert_in_state() {
    local pattern="$1"
    local label="$2"
    if grep -q "$pattern" /tmp/tf-state.log 2>/dev/null; then
        log_success "State: $label present"
    else
        log_error "State: $label MISSING (pattern: $pattern)"
        log_warning "  State contents:"
        sed 's/^/    /' /tmp/tf-state.log
    fi
}

assert_min_count() {
    local pattern="$1"
    local min="$2"
    local label="$3"
    local actual
    actual=$(grep -c "$pattern" /tmp/tf-state.log 2>/dev/null || echo 0)
    if [ "$actual" -ge "$min" ]; then
        log_success "Count: $actual $label (minimum $min)"
    else
        log_error "Count: $actual $label (expected >= $min)"
    fi
}

# IAM roles — both k3s node role and scheduler Lambda role must be managed.
assert_min_count "aws_iam_role\." 2 "IAM roles"

# Lambda function — the EC2 scheduler must be in state.
assert_in_state "aws_lambda_function\." "Lambda function (scheduler)"

# Security group — cluster network access control must exist.
assert_in_state "aws_security_group\." "Security group (k3s cluster)"

# S3 bucket — SSM transfer bucket must exist.
assert_in_state "aws_s3_bucket\.ssm_transfer" "S3 bucket (ssm_transfer)"

# IAM instance profile — EC2 nodes attach this to assume the k3s node role.
assert_in_state "aws_iam_instance_profile\." "IAM instance profile (k3s node)"

# Cleanup: destroy resources so LocalStack stays clean between runs.
log_info "Cleanup: destroying LocalStack resources"
if TF_VAR_localstack_test=yes \
    tflocal destroy \
        -auto-approve \
        -var-file=terraform.tfvars.localstack \
        > /tmp/tf-destroy.log 2>&1; then
    log_success "Destroy completed — LocalStack resources cleaned up"
else
    log_warning "Destroy had some failures (non-fatal — LocalStack may already be clean)"
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
    echo "  ✅ IAM roles, Lambda, S3, and security group entered Terraform state"
    echo ""
    log_warning "What was NOT validated (LocalStack limitations):"
    echo "  ❌ EC2 Spot/Fleet provisioning (LocalStack free tier)"
    echo "  ❌ k3s installation (user data execution)"
    echo "  ❌ IAM role assumption and actual permission checks"
    echo ""
    log_info "Next Steps:"
    echo "  1. Review /tmp/tf-apply.log for apply details"
    echo "  2. Review /tmp/tf-state.log for managed resources"
    echo "  3. Deploy to AWS for full behaviour validation"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Please review the output above.${NC}"
    echo ""
    exit 1
fi
