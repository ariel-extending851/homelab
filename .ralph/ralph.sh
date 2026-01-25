#!/bin/bash
set -euo pipefail

# ============================================================================
# RALPH LOOP v2.0 - Autonomous DevOps Agent with Safety Guardrails
# ============================================================================
# Description: Continuous integration loop with Phase 7 integration
# Features:
#   - Pre-commit review integration (/review command)
#   - Deployment verification (/deploy-verify command)
#   - State persistence across restarts
#   - Timestamped log rotation (keep last 10)
#   - CI status monitoring
#   - Failure tracking with abort logic (3 consecutive failures)
#   - BLOCKED marker detection in plan.md
# ============================================================================

# Configuration
MAX_LOOPS=10
STATE_FILE=".ralph/state.json"
LOG_DIR=".ralph/logs"
OPENCODE_DIR=".opencode"

echo "🤖 Ralph Loop v2.0 - Autonomous DevOps Agent"
echo "================================================"

# ============================================================================
# SAFETY CHECK: Verify required files exist
# ============================================================================
REQUIRED_FILES=(
    "$OPENCODE_DIR/instructions.md"
    "$OPENCODE_DIR/plan.md"
    "$OPENCODE_DIR/memory.md"
    ".ralph/PROMPT.md"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ FATAL: Required file missing: $file"
        echo "Cannot proceed without core context files."
        exit 1
    fi
done

# ============================================================================
# STATE INITIALIZATION
# ============================================================================
if [ ! -f "$STATE_FILE" ]; then
    echo "⚠️  No state file found. Creating initial state..."
    echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > "$STATE_FILE"
fi

COUNTER=$(jq -r '.iteration' "$STATE_FILE")
FAILURES=$(jq -r '.failures' "$STATE_FILE")
TOTAL_RUNS=$(jq -r '.total_runs' "$STATE_FILE")

# Safety: Max 3 consecutive failures = abort
if [ "$FAILURES" -ge 3 ]; then
    echo "❌ ABORT: 3 consecutive failures detected."
    echo ""
    echo "📋 Troubleshooting Steps:"
    echo "   1. Review logs in $LOG_DIR/"
    echo "   2. Check .opencode/last-review.md for blocking issues"
    echo "   3. Check .opencode/last-deploy-verify.md for deployment failures"
    echo "   4. Reset failures: jq '.failures = 0' $STATE_FILE > $STATE_FILE.tmp && mv $STATE_FILE.tmp $STATE_FILE"
    echo ""
    exit 1
fi

# ============================================================================
# LOGGING SETUP
# ============================================================================
mkdir -p "$LOG_DIR"

# Create timestamped log file
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/iteration-$TIMESTAMP.log"

# Log rotation: Keep only last 10 iterations
LOG_COUNT=$(ls -1 "$LOG_DIR" 2>/dev/null | wc -l)
if [ "$LOG_COUNT" -gt 10 ]; then
    echo "🗑️  Rotating logs (keeping last 10)..." | tee -a "$LOG_FILE"
    ls -1t "$LOG_DIR"/*.log 2>/dev/null | tail -n +11 | xargs -I {} rm -f {}
fi

# ============================================================================
# SESSION INFO
# ============================================================================
echo "📊 Session Info:" | tee -a "$LOG_FILE"
echo "   Starting Iteration: $COUNTER" | tee -a "$LOG_FILE"
echo "   Consecutive Failures: $FAILURES" | tee -a "$LOG_FILE"
echo "   Total Runs: $TOTAL_RUNS" | tee -a "$LOG_FILE"
echo "   Log File: $LOG_FILE" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# ============================================================================
# MAIN LOOP
# ============================================================================
while [ $COUNTER -lt $MAX_LOOPS ]; do
    let COUNTER=COUNTER+1
    let TOTAL_RUNS=TOTAL_RUNS+1
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
    echo "🔄 Iteration $COUNTER of $MAX_LOOPS (Failures: $FAILURES)" | tee -a "$LOG_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
    
    # ========================================================================
    # STEP 1: Check for BLOCKED marker in plan.md
    # ========================================================================
    echo "🔍 Step 1: Checking for blocked tasks..." | tee -a "$LOG_FILE"
    if grep -q "^BLOCKED:" "$OPENCODE_DIR/plan.md"; then
        BLOCKED_REASON=$(grep "^BLOCKED:" "$OPENCODE_DIR/plan.md" | head -1)
        echo "🛑 $BLOCKED_REASON" | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        echo "Human intervention required. Exiting Ralph Loop." | tee -a "$LOG_FILE"
        break
    fi
    echo "   ✅ No blocked tasks found." | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    
    # ========================================================================
    # STEP 2: Assemble context from .opencode/ directory
    # ========================================================================
    echo "📚 Step 2: Assembling context from .opencode/..." | tee -a "$LOG_FILE"
    FULL_CONTEXT=""
    for file in "${REQUIRED_FILES[@]}"; do
        FULL_CONTEXT+="$(cat "$file")"$'\n\n'"---"$'\n\n'
        echo "   📄 Loaded: $file" | tee -a "$LOG_FILE"
    done
    echo "   ✅ Context assembled successfully." | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    
    # ========================================================================
    # STEP 3: Execute OpenCode (NO --dangerously-skip-permissions)
    # ========================================================================
    echo "🚀 Step 3: Executing OpenCode..." | tee -a "$LOG_FILE"
    echo "   ⚠️  Note: Environment guardrails are ACTIVE (Section 6 of instructions.md)" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    
    # Write context to temporary file for opencode run
    CONTEXT_FILE="$(mktemp)"
    echo "$FULL_CONTEXT" > "$CONTEXT_FILE"
    
    # Use 'opencode run' for non-interactive execution (suppresses TUI)
    opencode run "$(cat "$CONTEXT_FILE")" 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=$?
    
    # Cleanup temporary context file
    rm -f "$CONTEXT_FILE"
    
    if [ $EXIT_CODE -ne 0 ]; then
        echo "⚠️  OpenCode exited with code $EXIT_CODE" | tee -a "$LOG_FILE"
        FAILURES=$((FAILURES + 1))
        jq ".iteration = $COUNTER | .failures = $FAILURES | .total_runs = $TOTAL_RUNS | .last_run = \"$(date -Iseconds)\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
        echo "⏳ Cooling down (5s) before retry..." | tee -a "$LOG_FILE"
        sleep 5
        continue
    fi
    echo "" | tee -a "$LOG_FILE"
    
    # ========================================================================
    # STEP 4: Pre-Commit Review (if changes detected)
    # ========================================================================
    if [ -n "$(git status --porcelain)" ]; then
        echo "📋 Step 4: Pre-Commit Review..." | tee -a "$LOG_FILE"
        echo "   Changes detected. Running /review command..." | tee -a "$LOG_FILE"
        
        # Execute /review command
        echo "/review" | opencode 2>&1 | tee -a "$LOG_FILE"
        
        # Check for HIGH severity blocking issues
        if [ -f "$OPENCODE_DIR/last-review.md" ]; then
            if grep -q "RECOMMENDATION: BLOCK" "$OPENCODE_DIR/last-review.md"; then
                echo "❌ Pre-commit review BLOCKED changes." | tee -a "$LOG_FILE"
                echo "   Review $OPENCODE_DIR/last-review.md for details." | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                
                # Show blocking issues summary
                echo "🚨 Blocking Issues Found:" | tee -a "$LOG_FILE"
                grep -A 5 "SEVERITY: HIGH" "$OPENCODE_DIR/last-review.md" | head -20 | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                
                FAILURES=$((FAILURES + 1))
                jq ".iteration = $COUNTER | .failures = $FAILURES | .total_runs = $TOTAL_RUNS | .last_run = \"$(date -Iseconds)\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
                
                echo "⏳ Cooling down (10s) before retry..." | tee -a "$LOG_FILE"
                sleep 10
                continue
            fi
        fi
        
        echo "   ✅ Pre-commit review passed." | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        
        # ====================================================================
        # STEP 5: Commit changes using /commit command
        # ====================================================================
        echo "💾 Step 5: Committing changes..." | tee -a "$LOG_FILE"
        echo "/commit" | opencode 2>&1 | tee -a "$LOG_FILE"
        
        if [ $? -ne 0 ]; then
            echo "⚠️  Commit failed." | tee -a "$LOG_FILE"
            FAILURES=$((FAILURES + 1))
            jq ".iteration = $COUNTER | .failures = $FAILURES | .total_runs = $TOTAL_RUNS | .last_run = \"$(date -Iseconds)\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
            echo "⏳ Cooling down (5s) before retry..." | tee -a "$LOG_FILE"
            sleep 5
            continue
        fi
        echo "   ✅ Changes committed successfully." | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
    else
        echo "📋 Step 4: No changes detected (skipping review/commit)." | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
    fi
    
    # ========================================================================
    # STEP 6: Deployment Verification (if k8s/ changes detected)
    # ========================================================================
    if git log -1 --name-only 2>/dev/null | grep -q "k8s/"; then
        echo "📦 Step 6: Deployment Verification..." | tee -a "$LOG_FILE"
        echo "   Kubernetes changes detected in last commit." | tee -a "$LOG_FILE"
        echo "   Waiting 15s for ArgoCD sync..." | tee -a "$LOG_FILE"
        sleep 15
        
        echo "   Running /deploy-verify command..." | tee -a "$LOG_FILE"
        echo "/deploy-verify" | opencode 2>&1 | tee -a "$LOG_FILE"
        
        # Check deploy-verify results
        if [ -f "$OPENCODE_DIR/last-deploy-verify.md" ]; then
            if grep -q "Status: ❌\|Health: Degraded\|Sync: OutOfSync" "$OPENCODE_DIR/last-deploy-verify.md"; then
                echo "⚠️  Deployment verification FAILED." | tee -a "$LOG_FILE"
                echo "   Review $OPENCODE_DIR/last-deploy-verify.md for details." | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                echo "🔄 Suggested Action: Consider rollback via:" | tee -a "$LOG_FILE"
                echo "   opencode '/rollback'" | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                
                FAILURES=$((FAILURES + 1))
                jq ".iteration = $COUNTER | .failures = $FAILURES | .total_runs = $TOTAL_RUNS | .last_run = \"$(date -Iseconds)\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
                
                echo "⏳ Cooling down (15s) before retry..." | tee -a "$LOG_FILE"
                sleep 15
                continue
            fi
        fi
        
        echo "   ✅ Deployment verification passed." | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
    else
        echo "📦 Step 6: No k8s changes detected (skipping deploy-verify)." | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
    fi
    
    # ========================================================================
    # STEP 7: CI Status Check
    # ========================================================================
    echo "🔍 Step 7: Checking CI status..." | tee -a "$LOG_FILE"
    if command -v gh &> /dev/null; then
        if gh run view --json status,conclusion 2>/dev/null | jq -e '.status == "completed" and .conclusion == "success"' > /dev/null 2>&1; then
            echo "   ✅ CI passed." | tee -a "$LOG_FILE"
            FAILURES=0  # Reset failure counter on CI success
        else
            CI_STATUS=$(gh run view --json status,conclusion 2>/dev/null | jq -r '.status // "unknown"')
            CI_CONCLUSION=$(gh run view --json status,conclusion 2>/dev/null | jq -r '.conclusion // "unknown"')
            echo "   ⚠️  CI status: $CI_STATUS (conclusion: $CI_CONCLUSION)" | tee -a "$LOG_FILE"
            
            # Only increment failures if CI actually failed (not pending)
            if [ "$CI_CONCLUSION" = "failure" ]; then
                FAILURES=$((FAILURES + 1))
            fi
        fi
    else
        echo "   ⚠️  gh CLI not found. Skipping CI check." | tee -a "$LOG_FILE"
    fi
    echo "" | tee -a "$LOG_FILE"
    
    # ========================================================================
    # STEP 8: Update State
    # ========================================================================
    jq ".iteration = $COUNTER | .failures = $FAILURES | .total_runs = $TOTAL_RUNS | .last_run = \"$(date -Iseconds)\"" "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
    
    # ========================================================================
    # STEP 9: Check if task completed (stop criteria)
    # ========================================================================
    echo "🎯 Step 9: Checking stop criteria..." | tee -a "$LOG_FILE"
    
    # Check if no pending changes AND last operation succeeded
    if [ $EXIT_CODE -eq 0 ] && [ -z "$(git status --porcelain)" ]; then
        echo "   ✅ Task completed. No pending changes." | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        echo "🏁 Ralph Loop completed successfully." | tee -a "$LOG_FILE"
        break
    fi
    
    echo "   ⏭️  Continuing to next iteration..." | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    
    echo "⏳ Cooling down (5s)..." | tee -a "$LOG_FILE"
    sleep 5
done

# ============================================================================
# FINAL SUMMARY
# ============================================================================
echo "" | tee -a "$LOG_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
echo "🛑 Ralph Loop Finished" | tee -a "$LOG_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$LOG_FILE"
echo "   Total Iterations: $COUNTER" | tee -a "$LOG_FILE"
echo "   Consecutive Failures: $FAILURES" | tee -a "$LOG_FILE"
echo "   Total Runs (All Time): $TOTAL_RUNS" | tee -a "$LOG_FILE"
echo "   Session Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

if [ $FAILURES -ge 3 ]; then
    echo "⚠️  WARNING: Loop terminated due to consecutive failures." | tee -a "$LOG_FILE"
    echo "   Review logs and resolve issues before restarting." | tee -a "$LOG_FILE"
    exit 1
fi

echo "✅ Session completed successfully." | tee -a "$LOG_FILE"
