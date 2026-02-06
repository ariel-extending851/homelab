#!/bin/bash
# ============================================================================
# Ralph v2.0 Test Automation - Helper Functions Library
# ============================================================================
# Purpose: Common functions for test execution, validation, and reporting
# Usage: Source this file in test scripts: source .ralph/test-automation/helpers.sh
# ============================================================================

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RALPH_DIR="$REPO_ROOT/.ralph"
OPENCODE_DIR="$REPO_ROOT/.opencode"
# shellcheck disable=SC2034  # Used by test scripts that source this file
TEST_AUTOMATION_DIR="$RALPH_DIR/test-automation"
TEST_ARTIFACTS_DIR="$RALPH_DIR/test-artifacts"
TEST_RESULTS_FILE="$TEST_ARTIFACTS_DIR/test-results.json"
TEST_REPORT_FILE="$TEST_ARTIFACTS_DIR/test-report.md"

# Test execution tracking
# shellcheck disable=SC2034  # Associative arrays used by generate_test_report()
declare -A TEST_RESULTS
# shellcheck disable=SC2034  # Associative arrays used by generate_test_report()
declare -A TEST_TIMES
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0
TESTS_TOTAL=0

# Colors for output
COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RESET='\033[0m'

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

# Print colored message
print_color() {
    local color=$1
    shift
    echo -e "${color}$*${COLOR_RESET}"
}

# Print section header
print_header() {
    local title=$1
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_color "$COLOR_BLUE" "$title"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Print test status
print_test_status() {
    local test_id=$1
    local status=$2
    local message=$3

    case $status in
        PASS)
            print_color "$COLOR_GREEN" "✅ $test_id: PASS - $message"
            ;;
        FAIL)
            print_color "$COLOR_RED" "❌ $test_id: FAIL - $message"
            ;;
        SKIP)
            print_color "$COLOR_YELLOW" "⏭️  $test_id: SKIP - $message"
            ;;
        *)
            echo "❓ $test_id: $status - $message"
            ;;
    esac
}

# ============================================================================
# ENVIRONMENT CHECKS
# ============================================================================

# Check if running in correct directory
check_repo_root() {
    if [ ! -f "$REPO_ROOT/.ralph/ralph.sh" ]; then
        print_color "$COLOR_RED" "❌ ERROR: Not in homelab repository root"
        print_color "$COLOR_YELLOW" "   Current: $REPO_ROOT"
        print_color "$COLOR_YELLOW" "   Expected: .ralph/ralph.sh should exist"
        exit 1
    fi
}

# Check required commands
check_prerequisites() {
    local missing=0

    echo "🔍 Checking prerequisites..."

    # Required
    if ! command -v jq &> /dev/null; then
        print_color "$COLOR_RED" "   ❌ jq not found (required)"
        missing=1
    else
        print_color "$COLOR_GREEN" "   ✅ jq found"
    fi

    if ! command -v git &> /dev/null; then
        print_color "$COLOR_RED" "   ❌ git not found (required)"
        missing=1
    else
        print_color "$COLOR_GREEN" "   ✅ git found"
    fi

    # Optional
    if ! command -v gh &> /dev/null; then
        print_color "$COLOR_YELLOW" "   ⚠️  gh CLI not found (optional - CI tests will be skipped)"
    else
        print_color "$COLOR_GREEN" "   ✅ gh CLI found"
    fi

    if [ $missing -eq 1 ]; then
        print_color "$COLOR_RED" "❌ Missing required prerequisites"
        exit 1
    fi

    echo ""
}

# Check if on safe branch
check_safe_branch() {
    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD)

    if [ "$current_branch" = "main" ]; then
        print_color "$COLOR_RED" "❌ ERROR: Cannot run tests on 'main' branch"
        print_color "$COLOR_YELLOW" "   Switch to test branch: git checkout -b test/ralph-v2-validation"
        exit 1
    fi

    print_color "$COLOR_GREEN" "✅ Current branch: $current_branch (safe)"
}

# ============================================================================
# TEST SETUP & TEARDOWN
# ============================================================================

# Initialize test environment
init_test_environment() {
    print_header "🚀 Initializing Test Environment"

    check_repo_root
    check_prerequisites
    check_safe_branch

    # Create test artifacts directory
    mkdir -p "$TEST_ARTIFACTS_DIR"

    # Backup plan.md
    if [ ! -f "$OPENCODE_DIR/plan.md.test-backup" ]; then
        cp "$OPENCODE_DIR/plan.md" "$OPENCODE_DIR/plan.md.test-backup"
        print_color "$COLOR_GREEN" "✅ Backed up plan.md"
    else
        print_color "$COLOR_YELLOW" "⚠️  plan.md.test-backup already exists (using existing backup)"
    fi

    # Reset state.json
    echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > "$RALPH_DIR/state.json"
    print_color "$COLOR_GREEN" "✅ Reset state.json"

    # Initialize test results
    echo '{"tests": [], "summary": {}}' > "$TEST_RESULTS_FILE"
    print_color "$COLOR_GREEN" "✅ Initialized test results file"

    # Record start time
    TEST_START_TIME=$(date +%s)

    echo ""
}

# Clean up test environment
cleanup_test_environment() {
    print_header "🧹 Cleaning Up Test Environment"

    # Restore plan.md
    if [ -f "$OPENCODE_DIR/plan.md.test-backup" ]; then
        mv "$OPENCODE_DIR/plan.md.test-backup" "$OPENCODE_DIR/plan.md"
        print_color "$COLOR_GREEN" "✅ Restored plan.md"
    fi

    # Reset state.json
    echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > "$RALPH_DIR/state.json"
    print_color "$COLOR_GREEN" "✅ Reset state.json"

    # Remove test files (but keep results)
    rm -f test-secret.yaml always-fail-secret.txt docs/test-*.md
    rm -rf k8s/apps/test-app
    print_color "$COLOR_GREEN" "✅ Removed test artifacts"

    # Unstage any test files
    git restore --staged . 2>/dev/null || true
    print_color "$COLOR_GREEN" "✅ Unstaged test files"

    echo ""
}

# ============================================================================
# TEST EXECUTION HELPERS
# ============================================================================

# Start a test
start_test() {
    local test_id=$1
    local test_name=$2

    print_header "📋 $test_id: $test_name"
    echo "⏱️  Start time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    TEST_START_TIME_SINGLE=$(date +%s)
}

# End a test with result
end_test() {
    local test_id=$1
    local status=$2  # PASS, FAIL, SKIP
    local message=$3

    local test_end_time
    test_end_time=$(date +%s)
    local test_duration=$((test_end_time - TEST_START_TIME_SINGLE))

    # shellcheck disable=SC2034  # Used by generate_test_report()
    TEST_RESULTS[$test_id]=$status
    # shellcheck disable=SC2034  # Used by generate_test_report()
    TEST_TIMES[$test_id]=$test_duration

    case $status in
        PASS)
            TESTS_PASSED=$((TESTS_PASSED + 1))
            ;;
        FAIL)
            TESTS_FAILED=$((TESTS_FAILED + 1))
            ;;
        SKIP)
            TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
            ;;
    esac

    echo ""
    print_test_status "$test_id" "$status" "$message"
    echo "⏱️  Duration: ${test_duration}s"
    echo ""

    # Record to JSON
    local result_json
    result_json=$(jq --arg id "$test_id" \
                      --arg status "$status" \
                      --arg message "$message" \
                      --argjson duration "$test_duration" \
                      '.tests += [{
                          "test_id": $id,
                          "status": $status,
                          "message": $message,
                          "duration": $duration
                      }]' "$TEST_RESULTS_FILE")
    echo "$result_json" > "$TEST_RESULTS_FILE"
}

# ============================================================================
# VALIDATION HELPERS
# ============================================================================

# Check if review blocked commit
check_review_blocked() {
    if [ ! -f "$OPENCODE_DIR/last-review.md" ]; then
        return 1
    fi

    grep -q "RECOMMENDATION: BLOCK" "$OPENCODE_DIR/last-review.md"
}

# Check if commit was created
check_commit_created() {
    local before_commit=$1
    local after_commit
    after_commit=$(git rev-parse HEAD)

    [ "$before_commit" != "$after_commit" ]
}

# Check state.json field
check_state_field() {
    local field=$1
    local expected=$2

    local actual
    actual=$(jq -r ".$field" "$RALPH_DIR/state.json")

    [ "$actual" = "$expected" ]
}

# Check log contains string
check_log_contains() {
    local search_string=$1
    local latest_log
    latest_log=$(ls -1t "$RALPH_DIR/logs"/*.log 2>/dev/null | head -1)

    if [ -z "$latest_log" ]; then
        return 1
    fi

    grep -q "$search_string" "$latest_log"
}

# ============================================================================
# REPORT GENERATION
# ============================================================================

# Generate final test report
generate_test_report() {
    print_header "📊 Generating Test Report"

    local total_duration=$(($(date +%s) - TEST_START_TIME))

    # Update summary in JSON
    local summary_json
    summary_json=$(jq --argjson passed "$TESTS_PASSED" \
                       --argjson failed "$TESTS_FAILED" \
                       --argjson skipped "$TESTS_SKIPPED" \
                       --argjson total "$TESTS_TOTAL" \
                       --argjson duration "$total_duration" \
                       '.summary = {
                           "passed": $passed,
                           "failed": $failed,
                           "skipped": $skipped,
                           "total": $total,
                           "duration": $duration,
                           "timestamp": now | strftime("%Y-%m-%d %H:%M:%S")
                       }' "$TEST_RESULTS_FILE")
    echo "$summary_json" > "$TEST_RESULTS_FILE"

    # Generate markdown report
    cat > "$TEST_REPORT_FILE" <<EOF
# Ralph v2.0 Test Execution Report

**Date:** $(date '+%Y-%m-%d %H:%M:%S')
**Duration:** ${total_duration}s ($(printf '%02d:%02d' $((total_duration/60)) $((total_duration%60))))
**Branch:** $(git rev-parse --abbrev-ref HEAD)
**Commit:** $(git rev-parse --short HEAD)

---

## Summary

| Metric | Count |
|--------|-------|
| **Total Tests** | $TESTS_TOTAL |
| **Passed** | $TESTS_PASSED ✅ |
| **Failed** | $TESTS_FAILED ❌ |
| **Skipped** | $TESTS_SKIPPED ⏭️ |
| **Success Rate** | $(if [ $TESTS_TOTAL -gt 0 ]; then awk "BEGIN {printf \"%.1f%%\", ($TESTS_PASSED/$TESTS_TOTAL)*100}"; else echo "N/A"; fi) |

---

## Test Results

| Test ID | Status | Duration | Message |
|---------|--------|----------|---------|
EOF

    # Add test results from JSON
    jq -r '.tests[] | "| \(.test_id) | \(.status) | \(.duration)s | \(.message) |"' "$TEST_RESULTS_FILE" >> "$TEST_REPORT_FILE"

    cat >> "$TEST_REPORT_FILE" <<EOF

---

## Detailed Results

$(jq -r '.tests[] | "### \(.test_id): \(.status)\n**Duration:** \(.duration)s  \n**Message:** \(.message)\n"' "$TEST_RESULTS_FILE")

---

## Artifacts

- **Test Results JSON:** \`.ralph/test-artifacts/test-results.json\`
- **Ralph Logs:** \`.ralph/logs/\`
- **Review Results:** \`.opencode/last-review.md\` (if exists)
- **Deploy Verify:** \`.opencode/last-deploy-verify.md\` (if exists)

---

**Overall Result:** $(if [ $TESTS_FAILED -eq 0 ]; then echo "✅ PASS"; else echo "❌ FAIL ($TESTS_FAILED failures)"; fi)
EOF

    print_color "$COLOR_GREEN" "✅ Test report generated: $TEST_REPORT_FILE"
    print_color "$COLOR_GREEN" "✅ Test results JSON: $TEST_RESULTS_FILE"
    echo ""

    # Display summary
    print_header "📊 Test Execution Summary"
    echo "Total Tests:   $TESTS_TOTAL"
    print_color "$COLOR_GREEN" "Passed:        $TESTS_PASSED ✅"
    print_color "$COLOR_RED" "Failed:        $TESTS_FAILED ❌"
    print_color "$COLOR_YELLOW" "Skipped:       $TESTS_SKIPPED ⏭️"
    echo "Success Rate:  $(if [ $TESTS_TOTAL -gt 0 ]; then awk "BEGIN {printf \"%.1f%%\", ($TESTS_PASSED/$TESTS_TOTAL)*100}"; else echo "N/A"; fi)"
    echo "Total Duration: ${total_duration}s ($(printf '%02d:%02d' $((total_duration/60)) $((total_duration%60))))"
    echo ""

    if [ $TESTS_FAILED -eq 0 ]; then
        print_color "$COLOR_GREEN" "🎉 ALL TESTS PASSED"
        return 0
    else
        print_color "$COLOR_RED" "❌ SOME TESTS FAILED"
        return 1
    fi
}

# ============================================================================
# RALPH EXECUTION HELPERS
# ============================================================================

# Run Ralph with timeout
run_ralph_with_timeout() {
    local timeout_seconds=$1
    local description=$2

    echo "🚀 Running Ralph Loop (timeout: ${timeout_seconds}s)"
    echo "   Description: $description"
    echo ""

    timeout "${timeout_seconds}s" "$RALPH_DIR/ralph.sh" 2>&1 | tee "$TEST_ARTIFACTS_DIR/ralph-output.log" || true
    local exit_code=${PIPESTATUS[0]}

    echo ""
    echo "Ralph exit code: $exit_code"
    return $exit_code
}

# Add task to plan.md
add_test_task() {
    local task_description=$1

    cat >> "$OPENCODE_DIR/plan.md" <<EOF

## Test Execution: Ralph v2.0 Validation
- [ ] $task_description
EOF
}

# ============================================================================
# EXPORT FUNCTIONS
# ============================================================================

# Make functions available to sourcing scripts
export -f print_color
export -f print_header
export -f print_test_status
export -f check_repo_root
export -f check_prerequisites
export -f check_safe_branch
export -f init_test_environment
export -f cleanup_test_environment
export -f start_test
export -f end_test
export -f check_review_blocked
export -f check_commit_created
export -f check_state_field
export -f check_log_contains
export -f generate_test_report
export -f run_ralph_with_timeout
export -f add_test_task

echo "✅ Ralph v2.0 Test Automation - Helper Functions Loaded"
