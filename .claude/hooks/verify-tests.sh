#!/usr/bin/env bash
# Stop hook — runs `make test-python` if Python files changed in this turn.
# Never modifies test files; only executes pytest in read-only verification mode.
# - Exit 0 if no .py changes (silent skip) or if tests pass.
# - Exit 2 if tests fail, surfacing pytest output to Claude so it can fix the
#   production code (NOT the tests).

set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Avoid infinite loops: if a previous Stop hook already triggered continuation,
# skip to let Claude finish.
input="$(cat)"
stop_active="$(printf '%s' "$input" | jq -r '.stop_hook_active // false')"
if [[ "$stop_active" == "true" ]]; then
  exit 0
fi

# Detect Python file changes (tracked + untracked) since last commit.
if ! command -v git >/dev/null 2>&1 || ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

changed_py="$( {
  git diff --name-only HEAD 2>/dev/null
  git ls-files --others --exclude-standard 2>/dev/null
} | grep -E '\.py$' || true)"

if [[ -z "$changed_py" ]]; then
  exit 0
fi

if ! command -v make >/dev/null 2>&1; then
  exit 0
fi

# Run the canonical Python test target. The Makefile owns coverage thresholds.
test_out="$(make test-python 2>&1)"
test_status=$?

if [[ $test_status -eq 0 ]]; then
  pass_line="$(printf '%s\n' "$test_out" | grep -E '^=+ .*passed' | tail -1 || true)"
  echo "verify-tests: pytest OK${pass_line:+ — $pass_line}"
  exit 0
fi

cat >&2 <<EOF
verify-tests: \`make test-python\` failed after Python files changed.

Changed files:
$changed_py

Pytest output:
$test_out

IMPORTANT: do NOT modify test files (test_*.py, tests/, bin/tests/) to make
this pass. Fix the production code in the changed files instead.
EOF
exit 2
