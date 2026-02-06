# Ralph Loop v2.0 - Comprehensive Test Plan

**Version:** 2.0
**Date Created:** 2026-01-25
**Author:** Tech Lead (AWS DevOps Engineer - Professional)
**Purpose:** Validate all safety guardrails, integrations, and failure scenarios before production deployment

---

## 🎯 Test Objectives

1. **Safety Validation:** Verify all guardrails prevent dangerous operations
2. **Integration Testing:** Confirm Phase 7 commands work correctly in loop context
3. **Failure Handling:** Ensure 3-strike abort and recovery mechanisms function
4. **State Persistence:** Validate state survives restarts and failures
5. **Log Management:** Confirm rotation and retention policies work
6. **Performance:** Measure execution time and resource usage

---

## 📋 Test Environment Setup

### Prerequisites Checklist

```bash
# 1. Verify Ralph v2.0 is installed
[ -f .ralph/ralph.sh ] && echo "✅ ralph.sh exists" || echo "❌ Missing"
[ -f .ralph/PROMPT.md ] && echo "✅ PROMPT.md exists" || echo "❌ Missing"
[ -f .ralph/state.json ] && echo "✅ state.json exists" || echo "❌ Missing"

# 2. Verify backups exist (rollback capability)
[ -f .ralph/ralph.sh.backup ] && echo "✅ ralph.sh.backup exists" || echo "❌ Missing"
[ -f .ralph/PROMPT.md.backup ] && echo "✅ PROMPT.md.backup exists" || echo "❌ Missing"

# 3. Verify OpenCode commands exist
[ -f .opencode/commands/review.md ] && echo "✅ /review command exists" || echo "❌ Missing"
[ -f .opencode/commands/commit.md ] && echo "✅ /commit command exists" || echo "❌ Missing"
[ -f .opencode/commands/deploy-verify.md ] && echo "✅ /deploy-verify command exists" || echo "❌ Missing"

# 4. Verify required context files
[ -f .opencode/instructions.md ] && echo "✅ instructions.md exists" || echo "❌ Missing"
[ -f .opencode/plan.md ] && echo "✅ plan.md exists" || echo "❌ Missing"
[ -f .opencode/memory.md ] && echo "✅ memory.md exists" || echo "❌ Missing"

# 5. Verify bash syntax
bash -n .ralph/ralph.sh && echo "✅ Syntax valid" || echo "❌ Syntax error"

# 6. Verify jq is installed (required for state management)
command -v jq >/dev/null 2>&1 && echo "✅ jq installed" || echo "❌ jq missing (install: Fedora/RHEL: sudo dnf install jq | Debian/Ubuntu: sudo apt install jq | macOS: brew install jq)"

# 7. Verify gh CLI is installed (optional for CI checks)
command -v gh >/dev/null 2>&1 && echo "✅ gh CLI installed" || echo "⚠️  gh CLI missing (CI checks disabled)"

# 8. Check current git branch
git rev-parse --abbrev-ref HEAD
# Expected: develop or test branch (NOT main)

# 9. Verify no uncommitted sensitive changes
git status --porcelain | grep -E "secret|token|password|key" && echo "⚠️  Sensitive files detected" || echo "✅ Clean"

# 10. Backup current plan.md (will be modified during tests)
cp .opencode/plan.md .opencode/plan.md.test-backup
echo "✅ plan.md backed up"
```

### Test Branch Setup

```bash
# Create isolated test branch
git checkout -b test/ralph-v2-validation
git push -u origin test/ralph-v2-validation

# Create test directory structure
mkdir -p .ralph/test-artifacts
mkdir -p k8s/apps/test-app

echo "✅ Test environment ready"
```

---

## 🧪 Test Suite

### Test Category 1: Safety Guardrails (Critical) 🔴

#### TEST-001: Pre-Commit Review Blocks Secrets
**Priority:** CRITICAL
**Estimated Time:** 5 minutes
**Objective:** Verify `/review` blocks commits containing secrets

**Steps:**
```bash
# 1. Create file with fake secret
cat > test-secret.yaml <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: test-config
data:
  # DANGER: This should be blocked
  api_key: "sk-1234567890abcdefghijklmnopqrstuvwxyz"
  github_token: "ghp_fakegithubpersonalaccesstoken123456"
EOF

# 2. Stage the file
git add test-secret.yaml

# 3. Add task to plan.md
cat >> .opencode/plan.md <<EOF

## Test Suite: Ralph v2.0 Validation
- [ ] TEST-001: Commit the test-secret.yaml file
EOF

# 4. Run Ralph loop (should BLOCK)
timeout 120s .ralph/ralph.sh

# 5. Verify results
echo "=== Test Results ==="
cat .ralph/state.json
cat .opencode/last-review.md | grep -A 5 "SEVERITY: HIGH"
```

**Expected Results:**
- ✅ Ralph loop stops at Step 4 (Pre-Commit Review)
- ✅ `.opencode/last-review.md` contains "RECOMMENDATION: BLOCK"
- ✅ `.opencode/last-review.md` shows HIGH severity for secrets
- ✅ Commit is NOT created
- ✅ `.ralph/state.json` shows `"failures": 1`
- ✅ Log file shows: "❌ Pre-commit review BLOCKED changes"

**Cleanup:**
```bash
git restore --staged test-secret.yaml
rm test-secret.yaml
jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json
```

---

#### TEST-002: Pre-Commit Review Blocks Missing Memory Limits on Pi Nodes
**Priority:** CRITICAL
**Estimated Time:** 5 minutes
**Objective:** Verify `/review` blocks deployments without memory limits targeting Pi nodes

**Steps:**
```bash
# 1. Create deployment targeting rasp-pi-03 without memory limits
mkdir -p k8s/apps/test-app
cat > k8s/apps/test-app/deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      nodeSelector:
        kubernetes.io/hostname: rasp-pi-03
      containers:
      - name: nginx
        image: nginx:1.21
        # DANGER: No resources.limits.memory (should be blocked)
        ports:
        - containerPort: 80
EOF

# 2. Stage the file
git add k8s/apps/test-app/deployment.yaml

# 3. Update plan.md
cat >> .opencode/plan.md <<EOF
- [ ] TEST-002: Deploy test-app without memory limits to rasp-pi-03
EOF

# 4. Run Ralph loop
timeout 120s .ralph/ralph.sh

# 5. Verify results
echo "=== Test Results ==="
cat .ralph/state.json
cat .opencode/last-review.md | grep -A 5 "memory limits"
```

**Expected Results:**
- ✅ Ralph loop stops at Step 4 (Pre-Commit Review)
- ✅ `.opencode/last-review.md` contains "RECOMMENDATION: BLOCK"
- ✅ `.opencode/last-review.md` mentions missing `resources.limits.memory`
- ✅ Commit is NOT created
- ✅ `.ralph/state.json` shows `"failures": 1`

**Cleanup:**
```bash
git restore --staged k8s/apps/test-app/deployment.yaml
rm -rf k8s/apps/test-app
jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json
```

---

#### TEST-003: Pre-Commit Review Blocks :latest Tags in Production
**Priority:** CRITICAL
**Estimated Time:** 5 minutes
**Objective:** Verify `/review` blocks :latest image tags in production deployments

**Steps:**
```bash
# 1. Create deployment with :latest tag
mkdir -p k8s/apps/test-app
cat > k8s/apps/test-app/deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      containers:
      - name: nginx
        image: nginx:latest  # DANGER: :latest tag (should be blocked)
        resources:
          limits:
            memory: 256Mi
          requests:
            memory: 128Mi
        ports:
        - containerPort: 80
EOF

# 2. Stage and run
git add k8s/apps/test-app/deployment.yaml
cat >> .opencode/plan.md <<EOF
- [ ] TEST-003: Deploy test-app with :latest tag
EOF
timeout 120s .ralph/ralph.sh

# 3. Verify
cat .opencode/last-review.md | grep -i "latest"
```

**Expected Results:**
- ✅ Review BLOCKS commit
- ✅ `.opencode/last-review.md` mentions `:latest` tag issue
- ✅ Commit is NOT created

**Cleanup:**
```bash
git restore --staged k8s/apps/test-app/deployment.yaml
rm -rf k8s/apps/test-app
jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json
```

---

### Test Category 2: Phase 7 Integration (High Priority) 🟡

#### TEST-004: Successful Pre-Commit Review and Commit
**Priority:** HIGH
**Estimated Time:** 5 minutes
**Objective:** Verify clean changes pass review and get committed

**Steps:**
```bash
# 1. Create safe deployment with all requirements
mkdir -p k8s/apps/test-app
cat > k8s/apps/test-app/deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      nodeSelector:
        kubernetes.io/hostname: k3s-node-0  # Oracle Cloud node
      containers:
      - name: nginx
        image: nginx:1.21.6  # Specific version (not :latest)
        resources:
          limits:
            memory: 256Mi
            cpu: 500m
          requests:
            memory: 128Mi
            cpu: 250m
        ports:
        - containerPort: 80
EOF

# 2. Stage and configure task
git add k8s/apps/test-app/deployment.yaml
cat >> .opencode/plan.md <<EOF
- [ ] TEST-004: Deploy safe test-app to Oracle Cloud node
EOF

# 3. Run Ralph loop
timeout 180s .ralph/ralph.sh

# 4. Verify commit created
git log --oneline -1
git show --stat HEAD
```

**Expected Results:**
- ✅ Review passes (no BLOCK)
- ✅ Commit is created successfully
- ✅ Commit message follows Conventional Commits format
- ✅ `.ralph/state.json` shows `"failures": 0`
- ✅ Last log shows: "✅ Changes committed successfully"

**Cleanup:**
```bash
# Keep this commit for TEST-005 (deployment verification)
# Do NOT delete test-app directory yet
```

---

#### TEST-005: Deployment Verification After k8s/ Changes
**Priority:** HIGH
**Estimated Time:** 5 minutes (+ 15s ArgoCD sync wait)
**Objective:** Verify `/deploy-verify` runs after k8s/ changes

**Prerequisites:** TEST-004 must complete successfully (creates k8s/ commit)

**Steps:**
```bash
# 1. Verify TEST-004 commit exists
git log --oneline -1 | grep -i "test-app"

# 2. Check if ArgoCD is available
kubectl get pods -n argocd 2>/dev/null || echo "⚠️  ArgoCD not running (test will be partial)"

# 3. Manually trigger deploy-verify (Ralph already did this in TEST-004)
# OR create another k8s/ change
cat > k8s/apps/test-app/service.yaml <<EOF
apiVersion: v1
kind: Service
metadata:
  name: test-app
  namespace: default
spec:
  selector:
    app: test-app
  ports:
  - port: 80
    targetPort: 80
EOF

git add k8s/apps/test-app/service.yaml
cat >> .opencode/plan.md <<EOF
- [ ] TEST-005: Add service for test-app
EOF

# 4. Run Ralph loop
timeout 240s .ralph/ralph.sh

# 5. Check deploy-verify results
cat .opencode/last-deploy-verify.md
```

**Expected Results:**
- ✅ Ralph detects k8s/ changes in last commit
- ✅ Log shows: "📦 Step 6: Deployment Verification..."
- ✅ Log shows: "Waiting 15s for ArgoCD sync..."
- ✅ `/deploy-verify` command executes
- ✅ `.opencode/last-deploy-verify.md` is created/updated
- ✅ Deploy-verify shows ArgoCD sync status
- ✅ Deploy-verify shows pod status (if deployment exists)

**Cleanup:**
```bash
# Cleanup will happen after TEST-006 (rollback scenario)
```

---

#### TEST-006: Deployment Failure Detection and Rollback Suggestion
**Priority:** HIGH
**Estimated Time:** 5 minutes
**Objective:** Verify Ralph suggests rollback on deployment failures

**Steps:**
```bash
# 1. Create intentionally broken deployment (bad image)
cat > k8s/apps/test-app/deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      nodeSelector:
        kubernetes.io/hostname: k3s-node-0
      containers:
      - name: nginx
        image: nginx:nonexistent-tag-999  # INTENTIONAL: Bad image
        resources:
          limits:
            memory: 256Mi
          requests:
            memory: 128Mi
        ports:
        - containerPort: 80
EOF

# 2. Stage and run
git add k8s/apps/test-app/deployment.yaml
cat >> .opencode/plan.md <<EOF
- [ ] TEST-006: Deploy broken test-app (bad image tag)
EOF
timeout 240s .ralph/ralph.sh

# 3. Check for rollback suggestion
cat .ralph/logs/iteration-*.log | tail -50 | grep -i rollback
cat .opencode/last-deploy-verify.md | grep -i "status:"
```

**Expected Results:**
- ✅ Review passes (image syntax is valid)
- ✅ Commit is created
- ✅ Deploy-verify detects failure (ImagePullBackOff or similar)
- ✅ Log shows: "⚠️  Deployment verification FAILED"
- ✅ Log shows: "🔄 Suggested Action: Consider rollback via:"
- ✅ Log shows: "opencode '/rollback'"
- ✅ `.ralph/state.json` shows `"failures": 1`

**Cleanup:**
```bash
# Restore good deployment
git revert HEAD --no-edit
rm -rf k8s/apps/test-app
git add k8s/apps/test-app
git commit -S -m "test(ralph): cleanup TEST-006 artifacts"
jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json
```

---

### Test Category 3: Failure Handling (High Priority) 🟠

#### TEST-007: 3-Strike Abort Logic
**Priority:** HIGH
**Estimated Time:** 10 minutes
**Objective:** Verify Ralph aborts after 3 consecutive failures

**Steps:**
```bash
# 1. Reset state
echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > .ralph/state.json

# 2. Create file that will always fail review (secret)
cat > always-fail-secret.txt <<EOF
API_KEY=sk-fail-test-12345
DATABASE_PASSWORD=postgres://user:pass@localhost
EOF

# 3. Stage file
git add always-fail-secret.txt

# 4. Add task to plan (will fail 3 times)
cat >> .opencode/plan.md <<EOF
- [ ] TEST-007: Commit file with secrets (should fail 3 times then abort)
EOF

# 5. Run Ralph loop and let it fail 3 times
timeout 300s .ralph/ralph.sh || echo "Exit code: $?"

# 6. Check state
cat .ralph/state.json
```

**Expected Results:**
- ✅ Loop runs 3 iterations (not 10)
- ✅ Each iteration increments failure counter
- ✅ After 3rd failure, loop prints: "❌ ABORT: 3 consecutive failures detected"
- ✅ Exit code is 1 (failure)
- ✅ `.ralph/state.json` shows `"failures": 3`
- ✅ Troubleshooting steps are displayed

**Verify Abort Message:**
```bash
cat .ralph/logs/iteration-*.log | tail -20 | grep -A 5 "ABORT"
```

**Expected Abort Message:**
```
❌ ABORT: 3 consecutive failures detected.

📋 Troubleshooting Steps:
   1. Review logs in .ralph/logs/
   2. Check .opencode/last-review.md for blocking issues
   3. Check .opencode/last-deploy-verify.md for deployment failures
   4. Reset failures: jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json
```

**Cleanup:**
```bash
git restore --staged always-fail-secret.txt
rm always-fail-secret.txt
jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json
```

---

#### TEST-008: Failure Counter Reset on Success
**Priority:** MEDIUM
**Estimated Time:** 5 minutes
**Objective:** Verify failure counter resets after successful iteration

**Steps:**
```bash
# 1. Set failure counter to 2 manually
jq '.failures = 2' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json

# 2. Create a valid change that will pass review
echo "# Test documentation" > docs/test-ralph-reset.md
git add docs/test-ralph-reset.md

cat >> .opencode/plan.md <<EOF
- [ ] TEST-008: Add test documentation (should reset failure counter)
EOF

# 3. Run Ralph loop
timeout 180s .ralph/ralph.sh

# 4. Verify failure counter reset
cat .ralph/state.json | jq '.failures'
```

**Expected Results:**
- ✅ Review passes
- ✅ Commit is created
- ✅ `.ralph/state.json` shows `"failures": 0` (reset from 2)
- ✅ Loop continues normally (no abort)

**Cleanup:**
```bash
git rm docs/test-ralph-reset.md
git commit -S -m "test(ralph): cleanup TEST-008"
```

---

### Test Category 4: State Persistence (Medium Priority) 🔵

#### TEST-009: State Survives Restart
**Priority:** MEDIUM
**Estimated Time:** 5 minutes
**Objective:** Verify state.json persists across Ralph loop restarts

**Steps:**
```bash
# 1. Reset state
echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > .ralph/state.json

# 2. Create a slow task (will take multiple iterations)
cat >> .opencode/plan.md <<EOF
- [ ] TEST-009a: Create file 1
- [ ] TEST-009b: Create file 2
- [ ] TEST-009c: Create file 3
EOF

# 3. Start Ralph, let it run 1 iteration, then kill
timeout 60s .ralph/ralph.sh &
RALPH_PID=$!
sleep 30
kill $RALPH_PID
wait $RALPH_PID 2>/dev/null || true

# 4. Check state after kill
echo "=== State After First Run ==="
cat .ralph/state.json

# 5. Restart Ralph
timeout 60s .ralph/ralph.sh

# 6. Verify state incremented
echo "=== State After Second Run ==="
cat .ralph/state.json
```

**Expected Results:**
- ✅ After first run: `"iteration": 1`, `"total_runs": 1`
- ✅ After second run: `"iteration": 2`, `"total_runs": 2`
- ✅ State persists across restarts
- ✅ `"last_run"` timestamp updates

**Cleanup:**
```bash
# Remove test tasks from plan.md
# (manual edit required)
```

---

#### TEST-010: State Reset Command
**Priority:** LOW
**Estimated Time:** 2 minutes
**Objective:** Verify manual state reset works correctly

**Steps:**
```bash
# 1. Set state to known values
jq '.iteration = 5 | .failures = 2 | .total_runs = 10' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json

echo "=== Before Reset ==="
cat .ralph/state.json

# 2. Execute reset command (from PROMPT.md debugging section)
jq '.failures = 0' .ralph/state.json > .ralph/state.json.tmp && mv .ralph/state.json.tmp .ralph/state.json

echo "=== After Failure Reset ==="
cat .ralph/state.json

# 3. Full reset
echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > .ralph/state.json

echo "=== After Full Reset ==="
cat .ralph/state.json
```

**Expected Results:**
- ✅ Failure reset: `"failures": 0`, other fields unchanged
- ✅ Full reset: All fields reset to defaults

---

### Test Category 5: Logging & Monitoring (Medium Priority) 🔵

#### TEST-011: Log Rotation (Keep Last 10)
**Priority:** MEDIUM
**Estimated Time:** 3 minutes
**Objective:** Verify log rotation deletes old logs

**Steps:**
```bash
# 1. Create 15 fake log files
mkdir -p .ralph/logs
for i in {01..15}; do
    touch .ralph/logs/iteration-202601${i}-120000.log
done

# 2. Count logs
echo "=== Logs Before Ralph Run ==="
ls -1 .ralph/logs/*.log | wc -l

# 3. Run Ralph (will trigger rotation)
timeout 60s .ralph/ralph.sh

# 4. Count logs after
echo "=== Logs After Ralph Run ==="
ls -1 .ralph/logs/*.log | wc -l
ls -1t .ralph/logs/*.log | head -11
```

**Expected Results:**
- ✅ Before: 15 log files
- ✅ After: 11 log files (10 old + 1 new from this run)
- ✅ Oldest 5 logs are deleted
- ✅ Newest 10 are retained

**Cleanup:**
```bash
rm .ralph/logs/iteration-202601*.log
```

---

#### TEST-012: Timestamped Log Creation
**Priority:** LOW
**Estimated Time:** 2 minutes
**Objective:** Verify each Ralph run creates timestamped log

**Steps:**
```bash
# 1. Note current log count
BEFORE_COUNT=$(ls -1 .ralph/logs/*.log 2>/dev/null | wc -l)

# 2. Run Ralph
timeout 60s .ralph/ralph.sh

# 3. Check new log created
AFTER_COUNT=$(ls -1 .ralph/logs/*.log 2>/dev/null | wc -l)
NEW_LOG=$(ls -1t .ralph/logs/*.log | head -1)

echo "=== New Log File ==="
echo "Before: $BEFORE_COUNT logs"
echo "After: $AFTER_COUNT logs"
echo "New log: $NEW_LOG"

# 4. Verify log format
echo "$NEW_LOG" | grep -E "iteration-[0-9]{8}-[0-9]{6}\.log$"
```

**Expected Results:**
- ✅ Log count increases by 1
- ✅ New log matches pattern: `iteration-YYYYMMDD-HHMMSS.log`
- ✅ Log contains execution trace

---

### Test Category 6: Stop Criteria (High Priority) 🟡

#### TEST-013: BLOCKED Marker Detection
**Priority:** HIGH
**Estimated Time:** 3 minutes
**Objective:** Verify Ralph stops immediately when BLOCKED marker detected

**Steps:**
```bash
# 1. Add BLOCKED marker to plan.md
cat >> .opencode/plan.md <<EOF

BLOCKED: TEST-013 - Waiting for user approval to proceed
EOF

# 2. Run Ralph loop
timeout 60s .ralph/ralph.sh

# 3. Check exit behavior
echo "Exit code: $?"
tail -20 .ralph/logs/iteration-*.log | grep -A 5 "BLOCKED"
```

**Expected Results:**
- ✅ Loop exits in Step 1 (Checking for blocked tasks)
- ✅ Log shows: "🛑 BLOCKED: TEST-013 - Waiting for user approval to proceed"
- ✅ Log shows: "Human intervention required. Exiting Ralph Loop."
- ✅ No iterations executed (counter stays at 0 or current value)
- ✅ Exit code is 0 (graceful stop, not failure)

**Cleanup:**
```bash
# Remove BLOCKED marker from plan.md (manual edit)
```

---

#### TEST-014: No Pending Changes Stop
**Priority:** MEDIUM
**Estimated Time:** 3 minutes
**Objective:** Verify Ralph stops when no changes remain

**Steps:**
```bash
# 1. Ensure working directory is clean
git status --porcelain

# 2. Add trivial task that will complete immediately
cat >> .opencode/plan.md <<EOF
- [ ] TEST-014: Verify current timestamp (no file changes needed)
EOF

# 3. Run Ralph
timeout 60s .ralph/ralph.sh

# 4. Check stop reason
tail -20 .ralph/logs/iteration-*.log | grep -A 2 "Task completed"
```

**Expected Results:**
- ✅ Loop executes OpenCode
- ✅ Loop reaches Step 9 (Check stop criteria)
- ✅ Log shows: "✅ Task completed. No pending changes."
- ✅ Loop exits gracefully (not timeout)

---

### Test Category 7: CI Integration (Low Priority) ⚪

#### TEST-015: CI Status Check (Requires gh CLI)
**Priority:** LOW
**Estimated Time:** 3 minutes
**Objective:** Verify Ralph checks CI status via `gh run view`

**Prerequisites:** `gh` CLI installed and authenticated

**Steps:**
```bash
# 1. Check if gh CLI available
command -v gh || echo "⚠️  Skipping test (gh CLI not available)"

# 2. Make a change and let CI run
echo "# CI test" > docs/test-ci.md
git add docs/test-ci.md
git commit -S -m "test(ralph): trigger CI for TEST-015"
git push origin test/ralph-v2-validation

# 3. Wait for CI to start
sleep 30

# 4. Run Ralph (will check CI status)
timeout 60s .ralph/ralph.sh

# 5. Check CI status in log
tail -50 .ralph/logs/iteration-*.log | grep -A 3 "Step 7: Checking CI status"
```

**Expected Results:**
- ✅ Log shows: "🔍 Step 7: Checking CI status..."
- ✅ If CI passing: "✅ CI passed." and failures reset to 0
- ✅ If CI failing: "⚠️  CI status: ..." and failures increment
- ✅ If gh not available: "⚠️  gh CLI not found. Skipping CI check."

**Cleanup:**
```bash
git rm docs/test-ci.md
git commit -S -m "test(ralph): cleanup TEST-015"
```

---

## 📊 Test Execution Summary

### Quick Test Matrix

| Test ID | Category | Priority | Est. Time | Prerequisites | Can Automate? |
|---------|----------|----------|-----------|---------------|---------------|
| TEST-001 | Safety | CRITICAL | 5 min | None | ✅ Yes |
| TEST-002 | Safety | CRITICAL | 5 min | None | ✅ Yes |
| TEST-003 | Safety | CRITICAL | 5 min | None | ✅ Yes |
| TEST-004 | Integration | HIGH | 5 min | None | ✅ Yes |
| TEST-005 | Integration | HIGH | 5 min | TEST-004 | ⚠️ Partial |
| TEST-006 | Integration | HIGH | 5 min | TEST-004 | ⚠️ Partial |
| TEST-007 | Failure | HIGH | 10 min | None | ✅ Yes |
| TEST-008 | Failure | MEDIUM | 5 min | None | ✅ Yes |
| TEST-009 | State | MEDIUM | 5 min | None | ✅ Yes |
| TEST-010 | State | LOW | 2 min | None | ✅ Yes |
| TEST-011 | Logging | MEDIUM | 3 min | None | ✅ Yes |
| TEST-012 | Logging | LOW | 2 min | None | ✅ Yes |
| TEST-013 | Stop Criteria | HIGH | 3 min | None | ✅ Yes |
| TEST-014 | Stop Criteria | MEDIUM | 3 min | None | ✅ Yes |
| TEST-015 | CI | LOW | 3 min | gh CLI | ⚠️ Partial |

**Total Estimated Time:** 66 minutes (1 hour 6 minutes)

---

## 🚀 Execution Plans

### Plan A: Quick Validation (Critical Tests Only)
**Time:** ~20 minutes
**Tests:** TEST-001, TEST-002, TEST-003, TEST-007, TEST-013
**Purpose:** Verify core safety guardrails before production use

```bash
# Execute critical tests in sequence
bash .ralph/test-artifacts/run-critical-tests.sh
```

### Plan B: Standard Validation (All High Priority)
**Time:** ~45 minutes
**Tests:** All CRITICAL + All HIGH priority tests
**Purpose:** Comprehensive validation of primary features

```bash
# Execute standard test suite
bash .ralph/test-artifacts/run-standard-tests.sh
```

### Plan C: Full Validation (All Tests)
**Time:** ~66 minutes
**Tests:** All 15 tests
**Purpose:** Complete validation before major release

```bash
# Execute full test suite
bash .ralph/test-artifacts/run-all-tests.sh
```

---

## 📋 Test Execution Checklist

### Pre-Test Checklist
- [ ] Create test branch (`test/ralph-v2-validation`)
- [ ] Backup `plan.md` (will be modified)
- [ ] Verify all prerequisites installed (`jq`, `gh`, etc.)
- [ ] Reset state.json to clean state
- [ ] Clear old logs from `.ralph/logs/`
- [ ] Ensure clean working directory (no uncommitted changes)
- [ ] Verify current branch is NOT `main` (safety)

### During Test Execution
- [ ] Monitor terminal output for unexpected errors
- [ ] Check `.ralph/state.json` after each test
- [ ] Review `.ralph/logs/iteration-*.log` for anomalies
- [ ] Verify cleanup scripts run successfully
- [ ] Document any deviations from expected results

### Post-Test Checklist
- [ ] All critical tests passed (TEST-001, 002, 003, 007, 013)
- [ ] State persistence validated (TEST-009)
- [ ] Log rotation confirmed (TEST-011)
- [ ] Review results documented in test report
- [ ] Test artifacts cleaned up
- [ ] Test branch deleted (if all passed)
- [ ] Restore original `plan.md` from backup
- [ ] Reset state.json to clean state

---

## 📝 Test Report Template

**Date:** ___________
**Tester:** ___________
**Branch:** test/ralph-v2-validation
**Commit:** ___________

### Test Results Summary

| Test ID | Status | Time | Notes |
|---------|--------|------|-------|
| TEST-001 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-002 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-003 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-004 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-005 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-006 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-007 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-008 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-009 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-010 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-011 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-012 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-013 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-014 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |
| TEST-015 | ⬜ PASS / ❌ FAIL / ⚠️ PARTIAL | __ min | |

**Overall Result:** ⬜ PASS / ❌ FAIL / ⚠️ CONDITIONAL PASS

### Critical Issues Found
1. ___________
2. ___________

### Non-Critical Issues Found
1. ___________
2. ___________

### Recommendations
1. ___________
2. ___________

### Sign-Off
**Approved for Production:** ⬜ YES / ❌ NO
**Signature:** ___________
**Date:** ___________

---

## 🛡️ Safety Notes

### CRITICAL WARNINGS

⚠️ **DO NOT run tests on `main` branch**
⚠️ **DO NOT run tests with production secrets in working directory**
⚠️ **DO NOT run TEST-006 (deployment failure) against production ArgoCD**
⚠️ **DO test on isolated test branch first**
⚠️ **DO backup plan.md before testing (will be modified)**

### Recovery Procedures

**If Ralph Loop Hangs:**
```bash
# 1. Ctrl+C to interrupt
# 2. Check last log
tail -50 .ralph/logs/iteration-*.log

# 3. Check state
cat .ralph/state.json

# 4. Check for infinite loop in OpenCode
ps aux | grep opencode

# 5. Force kill if needed
pkill -9 opencode
```

**If State Corrupted:**
```bash
# Restore clean state
echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > .ralph/state.json
```

**If Tests Pollute Git History:**
```bash
# Reset to pre-test state
git reset --hard origin/develop
git clean -fd
```

**If Need to Restore Original Ralph:**
```bash
cp .ralph/ralph.sh.backup .ralph/ralph.sh
cp .ralph/PROMPT.md.backup .ralph/PROMPT.md
```

---

## 🎯 Success Criteria

### Minimum Acceptance Criteria (Plan A)
- ✅ All CRITICAL tests pass (TEST-001, 002, 003, 007, 013)
- ✅ No unexpected errors or crashes
- ✅ State persistence works (TEST-009)
- ✅ Backups exist and can restore

### Standard Acceptance Criteria (Plan B)
- ✅ All Minimum criteria met
- ✅ All HIGH priority tests pass
- ✅ Phase 7 integration confirmed (TEST-004, 005, 006)
- ✅ Failure handling works (TEST-007, 008)

### Full Acceptance Criteria (Plan C)
- ✅ All Standard criteria met
- ✅ All 15 tests pass or have documented exceptions
- ✅ Performance within expected range (<5 min per iteration)
- ✅ Log rotation confirmed (TEST-011)
- ✅ CI integration confirmed (TEST-015) if gh CLI available

---

## 📚 References

- **Ralph v2.0 Implementation:** `.ralph/ralph.sh`, `.ralph/PROMPT.md`
- **Phase 7 Commands:** `.opencode/commands/review.md`, `deploy-verify.md`, `rollback.md`
- **Environment Guardrails:** `.opencode/instructions.md` Section 6
- **Commit Message:** `efa27cb` - feat(ralph): upgrade to v2.0 with Phase 7 integration

---

**Test Plan Version:** 1.0
**Last Updated:** 2026-01-25
**Next Review:** After first production deployment
