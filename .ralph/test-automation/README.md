# Ralph v2.0 Test Automation

**Purpose:** Automated test execution for Ralph Loop v2.0 validation
**Location:** `.ralph/test-automation/`
**Documentation:** `.ralph/TEST-PLAN.md` (manual test procedures)

---

## 📋 Overview

This directory contains automated test scripts for validating Ralph v2.0 safety guardrails, Phase 7 integration, and failure handling.

### Available Scripts

| Script | Purpose | Duration | Tests |
|--------|---------|----------|-------|
| **`run-critical-tests.sh`** | Plan A: Critical safety tests | ~20 min | 5 tests (TEST-001, 002, 003, 007, 013) |
| **`helpers.sh`** | Common functions library | N/A | Sourced by other scripts |
| **`cleanup.sh`** | Clean up test artifacts | <1 min | N/A |

---

## 🚀 Quick Start

### Run Critical Tests (Plan A)

```bash
# From repository root
cd /path/to/homelab

# Create test branch (REQUIRED - prevents pollution of develop/main)
git checkout -b test/ralph-v2-validation

# Run critical tests
.ralph/test-automation/run-critical-tests.sh

# View results
cat .ralph/test-artifacts/test-report.md

# Cleanup
.ralph/test-automation/cleanup.sh

# Return to develop
git checkout develop
git branch -D test/ralph-v2-validation
```

---

## 📚 Detailed Usage

### Script 1: run-critical-tests.sh (Plan A)

**Purpose:** Execute 5 critical safety tests to verify core guardrails
**Duration:** ~20 minutes
**Tests Included:**
- TEST-001: Secrets detection (blocks API keys, tokens)
- TEST-002: Memory limits enforcement (blocks missing limits on Pi nodes)
- TEST-003: :latest tag blocking (enforces specific versions)
- TEST-007: 3-strike abort logic (prevents infinite failures)
- TEST-013: BLOCKED marker detection (enables human-in-the-loop)

**Prerequisites:**
- Must be on non-main branch (safety check)
- `jq` command installed (required)
- `git` command installed (required)
- Clean working directory (no uncommitted changes)

**Usage:**
```bash
# Standard execution
.ralph/test-automation/run-critical-tests.sh

# The script will:
# 1. Check prerequisites (jq, git, safe branch)
# 2. Backup plan.md
# 3. Reset state.json
# 4. Execute 5 tests sequentially
# 5. Generate test report
# 6. Restore environment
```

**Output Files:**
- `.ralph/test-artifacts/test-results.json` - Machine-readable results
- `.ralph/test-artifacts/test-report.md` - Human-readable report
- `.ralph/logs/iteration-*.log` - Ralph execution logs

**Exit Codes:**
- `0` - All tests passed
- `1` - One or more tests failed or prerequisites missing

---

### Script 2: helpers.sh (Library)

**Purpose:** Common functions for test execution, validation, and reporting
**Usage:** Sourced by other scripts (not executed directly)

**Key Functions:**
```bash
# Environment setup
init_test_environment()      # Initialize test environment
cleanup_test_environment()   # Restore environment after tests
check_prerequisites()        # Verify jq, git, gh CLI

# Test execution
start_test(test_id, name)    # Begin a test case
end_test(test_id, status, msg) # End test with result (PASS/FAIL/SKIP)
run_ralph_with_timeout(sec, desc) # Execute Ralph with timeout

# Validation
check_review_blocked()       # Verify /review blocked commit
check_commit_created(before) # Verify commit was created
check_state_field(field, expected) # Verify state.json field
check_log_contains(string)   # Check if log contains string

# Reporting
generate_test_report()       # Generate markdown and JSON reports
print_test_status(id, status, msg) # Print colored test result
```

**Colors:**
- 🟢 Green: Success (PASS)
- 🔴 Red: Failure (FAIL)
- 🟡 Yellow: Skipped (SKIP)
- 🔵 Blue: Headers and info

---

### Script 3: cleanup.sh (Cleanup)

**Purpose:** Clean up test artifacts and restore environment
**Duration:** <1 minute

**What It Does:**
- Restores `plan.md` from backup
- Resets `state.json` to clean state
- Removes test files (test-secret.yaml, always-fail-secret.txt, etc.)
- Removes test-app directory (k8s/apps/test-app)
- Unstages any pending git changes
- Preserves test results and logs (manual deletion required)

**Usage:**
```bash
# Standard cleanup
.ralph/test-automation/cleanup.sh

# Complete cleanup (including results)
.ralph/test-automation/cleanup.sh
rm -rf .ralph/test-artifacts
rm -f .ralph/logs/*.log
```

---

## 📊 Test Results

### Test Report Location

After running tests, results are available in:

```
.ralph/test-artifacts/
├── test-results.json    # Machine-readable (JSON)
├── test-report.md       # Human-readable (Markdown)
└── ralph-output.log     # Last Ralph execution output
```

### Test Report Format

**test-report.md** contains:
- Execution summary (passed/failed/skipped counts)
- Individual test results table
- Detailed test descriptions
- Artifacts locations
- Overall pass/fail status

**Example:**
```markdown
# Ralph v2.0 Test Execution Report

**Date:** 2026-01-25 12:45:00
**Duration:** 1245s (20:45)
**Branch:** test/ralph-v2-validation
**Commit:** abc1234

## Summary

| Metric | Count |
|--------|-------|
| **Total Tests** | 5 |
| **Passed** | 5 ✅ |
| **Failed** | 0 ❌ |
| **Skipped** | 0 ⏭️ |
| **Success Rate** | 100.0% |

## Test Results

| Test ID | Status | Duration | Message |
|---------|--------|----------|---------|
| TEST-001 | PASS | 120s | Review successfully blocked secrets |
| TEST-002 | PASS | 115s | Review successfully blocked missing memory limits |
...
```

### JSON Results Format

**test-results.json** structure:
```json
{
  "tests": [
    {
      "test_id": "TEST-001",
      "status": "PASS",
      "message": "Review successfully blocked secrets",
      "duration": 120
    }
  ],
  "summary": {
    "passed": 5,
    "failed": 0,
    "skipped": 0,
    "total": 5,
    "duration": 1245,
    "timestamp": "2026-01-25 12:45:00"
  }
}
```

---

## 🔧 Configuration

### Environment Variables

```bash
# Override repository root (auto-detected by default)
export REPO_ROOT=/path/to/homelab

# Override test timeout (default: 120s per test)
export TEST_TIMEOUT=180
```

### Test Customization

To modify tests, edit the respective script:
```bash
# Edit critical tests
nvim .ralph/test-automation/run-critical-tests.sh

# Each test is a bash function:
# - test_001_secrets_detection()
# - test_002_memory_limits()
# - test_003_latest_tags()
# - test_007_three_strike_abort()
# - test_013_blocked_marker()
```

---

## 🛡️ Safety Features

### Automatic Safety Checks

1. **Branch Protection:**
   - Refuses to run on `main` branch
   - Requires test branch creation

2. **Backup & Restore:**
   - Automatically backs up `plan.md`
   - Restores on cleanup or failure

3. **Isolation:**
   - All test files use test-* prefixes
   - Cleanup removes all test artifacts

4. **No Production Impact:**
   - Tests use fake secrets (not real)
   - Tests use test-app (not real deployments)
   - State.json reset after tests

---

## 📝 Writing Custom Tests

### Template for New Test

```bash
test_XXX_test_name() {
    start_test "TEST-XXX" "Human Readable Test Name"

    # 1. Setup test artifacts
    cat > test-file.yaml <<EOF
    # test content
EOF

    git add test-file.yaml
    add_test_task "TEST-XXX: Description of task"

    # 2. Record initial state
    local before_commit
    before_commit=$(git rev-parse HEAD)

    # 3. Execute Ralph
    run_ralph_with_timeout 120 "TEST-XXX: What should happen"

    # 4. Validate results
    local test_passed=true
    local failure_reasons=()

    if ! some_check; then
        test_passed=false
        failure_reasons+=("Check failed")
    fi

    # 5. Cleanup
    git restore --staged test-file.yaml 2>/dev/null || true
    rm -f test-file.yaml
    jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json

    # 6. Report result
    if $test_passed; then
        end_test "TEST-XXX" "PASS" "Success message"
    else
        end_test "TEST-XXX" "FAIL" "${failure_reasons[*]}"
    fi
}
```

### Adding Test to Execution

```bash
# In main() function, add:
test_XXX_test_name
```

---

## 🔍 Troubleshooting

### Issue: "jq not found"

**Solution:**
```bash
# Fedora/RHEL
sudo dnf install jq

# Debian/Ubuntu
sudo apt install jq

# macOS
brew install jq
```

### Issue: "Cannot run tests on 'main' branch"

**Solution:**
```bash
# Create test branch
git checkout -b test/ralph-v2-validation

# Then re-run tests
.ralph/test-automation/run-critical-tests.sh
```

### Issue: "Test hangs or times out"

**Cause:** Ralph Loop stuck in infinite loop or waiting for input
**Solution:**
1. Press Ctrl+C to interrupt
2. Check latest log: `tail -50 .ralph/logs/iteration-*.log | tail -1`
3. Run cleanup: `.ralph/test-automation/cleanup.sh`
4. Investigate issue in Ralph implementation

### Issue: "plan.md.test-backup already exists"

**Cause:** Previous test run did not clean up
**Solution:**
```bash
# Manual cleanup
.ralph/test-automation/cleanup.sh

# Or force remove backup
rm .opencode/plan.md.test-backup
```

### Issue: "Tests fail unexpectedly"

**Debugging Steps:**
1. Check test report: `cat .ralph/test-artifacts/test-report.md`
2. Check Ralph logs: `ls -lt .ralph/logs/ | head -5`
3. Check review results: `cat .opencode/last-review.md`
4. Check state: `cat .ralph/state.json`
5. Run cleanup: `.ralph/test-automation/cleanup.sh`
6. Re-run specific test manually (see TEST-PLAN.md)

---

## 📈 Performance

### Expected Durations

| Test | Expected Duration | Tolerance |
|------|-------------------|-----------|
| TEST-001 (Secrets) | 120s | ±20s |
| TEST-002 (Memory) | 120s | ±20s |
| TEST-003 (:latest) | 120s | ±20s |
| TEST-007 (3-Strike) | 300s | ±30s |
| TEST-013 (BLOCKED) | 60s | ±10s |
| **Total Plan A** | **720s (12min)** | **±2min** |

### Resource Usage

- **Disk Space:** ~5MB (logs + artifacts)
- **Memory:** Minimal (bash scripts)
- **CPU:** Depends on OpenCode execution

---

## 🎓 AWS DevOps Exam Parallels

### Test Automation Alignment

| Test | AWS Service Equivalent |
|------|------------------------|
| Critical Tests | CodeBuild test reports |
| Helpers Library | Lambda Layers (shared code) |
| Test Reports | CodeBuild batch reports |
| Cleanup Script | CloudFormation custom resources (cleanup) |

### CI/CD Integration

These scripts can be integrated into GitHub Actions:

```yaml
name: Ralph v2.0 Validation
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install jq
        run: sudo apt install -y jq
      - name: Run Critical Tests
        run: .ralph/test-automation/run-critical-tests.sh
      - name: Upload Test Report
        uses: actions/upload-artifact@v2
        with:
          name: test-report
          path: .ralph/test-artifacts/
```

---

## 📚 Related Documentation

- **Test Plan:** `.ralph/TEST-PLAN.md` - Comprehensive test plan (15 tests)
- **Ralph v2.0:** `.ralph/ralph.sh` - Ralph Loop implementation
- **PROMPT:** `.ralph/PROMPT.md` - Ralph autonomous mode instructions
- **Commands:** `.opencode/commands/` - Phase 7 commands (/review, /deploy-verify, /rollback)

---

## ✅ Success Criteria

### Critical Tests Pass

All 5 critical tests must pass for production deployment:
- ✅ TEST-001: Secrets blocked
- ✅ TEST-002: Memory limits enforced
- ✅ TEST-003: :latest tags blocked
- ✅ TEST-007: 3-strike abort works
- ✅ TEST-013: BLOCKED marker detected

### Test Report Generated

- ✅ test-report.md created
- ✅ test-results.json created
- ✅ All tests have PASS/FAIL status
- ✅ Success rate displayed

### Environment Restored

- ✅ plan.md restored from backup
- ✅ state.json reset to clean state
- ✅ Test files removed
- ✅ Git staging cleared

---

**Version:** 1.0
**Last Updated:** 2026-01-25
**Maintainer:** Tech Lead (AWS DevOps Engineer - Professional)
