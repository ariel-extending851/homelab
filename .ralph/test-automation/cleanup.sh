#!/bin/bash
# ============================================================================
# Ralph v2.0 Test Automation - Cleanup Script
# ============================================================================
# Purpose: Clean up test artifacts and restore environment
# Usage: .ralph/test-automation/cleanup.sh
# ============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RALPH_DIR="$REPO_ROOT/.ralph"
OPENCODE_DIR="$REPO_ROOT/.opencode"

echo "🧹 Ralph v2.0 Test Cleanup"
echo "=========================="
echo ""

# Restore plan.md
if [ -f "$OPENCODE_DIR/plan.md.test-backup" ]; then
    mv "$OPENCODE_DIR/plan.md.test-backup" "$OPENCODE_DIR/plan.md"
    echo "✅ Restored plan.md from backup"
else
    echo "⚠️  No plan.md backup found (skipping)"
fi

# Reset state.json
echo '{"iteration": 0, "last_task": "", "failures": 0, "last_run": "", "total_runs": 0}' > "$RALPH_DIR/state.json"
echo "✅ Reset state.json to clean state"

# Remove test files
rm -f "$REPO_ROOT/test-secret.yaml"
rm -f "$REPO_ROOT/always-fail-secret.txt"
rm -f "$REPO_ROOT/docs/test-"*.md
echo "✅ Removed test files"

# Remove test-app directory
if [ -d "$REPO_ROOT/k8s/apps/test-app" ]; then
    rm -rf "$REPO_ROOT/k8s/apps/test-app"
    echo "✅ Removed k8s/apps/test-app"
fi

# Unstage any test files
cd "$REPO_ROOT"
git restore --staged . 2>/dev/null || true
echo "✅ Unstaged any pending changes"

# Clear test artifacts (but keep results)
if [ -d "$RALPH_DIR/test-artifacts" ]; then
    echo ""
    echo "📊 Test Artifacts Summary:"
    if [ -f "$RALPH_DIR/test-artifacts/test-report.md" ]; then
        echo "   - Test Report: .ralph/test-artifacts/test-report.md"
    fi
    if [ -f "$RALPH_DIR/test-artifacts/test-results.json" ]; then
        echo "   - Test Results: .ralph/test-artifacts/test-results.json"
    fi
    echo ""
    echo "   To remove test results:"
    echo "   rm -rf $RALPH_DIR/test-artifacts"
fi

# Show Ralph logs
if [ -d "$RALPH_DIR/logs" ]; then
    LOG_COUNT=$(ls -1 "$RALPH_DIR/logs"/*.log 2>/dev/null | wc -l)
    echo "📜 Ralph Logs: $LOG_COUNT files in .ralph/logs/"
    echo "   To clear logs: rm -f $RALPH_DIR/logs/*.log"
fi

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Environment Status:"
echo "   - plan.md: Restored"
echo "   - state.json: Reset"
echo "   - Test files: Removed"
echo "   - Git staging: Cleared"
echo "   - Test artifacts: Preserved (manual deletion required)"
echo ""
