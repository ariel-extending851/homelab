#!/usr/bin/env bash
# Stop hook — runs pytest scoped to the Python files changed in this turn.
# This is a fast feedback signal, NOT a coverage gate. The full suite + 70%
# coverage gate runs in CI (`make test-python` in ci-validation.yml).
#
# Mapping rule: for each changed *.py file, run the matching `bin/tests/test_<name>.py`
# if it exists. If the changed file is itself a test, run it directly.
#
# - Exit 0 if no relevant tests can be located (silent skip) or if they pass.
# - Exit 2 if any test fails, surfacing pytest output. Claude must fix the
#   production code, NOT the tests.

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

# Resolve each changed file to a test target. Tests run themselves; non-test
# scripts map to bin/tests/test_<basename>.py if present.
test_targets=""
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  base="$(basename "$f" .py)"
  if [[ "$f" =~ (^|/)test_.*\.py$ || "$f" =~ /tests/.*\.py$ ]]; then
    test_targets="$test_targets $f"
  else
    candidate="bin/tests/test_${base}.py"
    [[ -f "$candidate" ]] && test_targets="$test_targets $candidate"
  fi
done <<< "$changed_py"

# Deduplicate and trim. Word-splitting is intentional — $test_targets is a
# space-separated list of paths, one per pytest argument.
# shellcheck disable=SC2086
test_targets="$(printf '%s\n' $test_targets | awk 'NF && !seen[$0]++' | tr '\n' ' ')"

if [[ -z "${test_targets// /}" ]]; then
  # No test file maps to the changes — skip silently.
  exit 0
fi

if ! command -v mise >/dev/null 2>&1; then
  exit 0
fi

# Run pytest fast: stop on first failure, no coverage gate. Word-splitting on
# $test_targets is intentional — each path is a separate pytest argument.
# shellcheck disable=SC2086
test_out="$(mise exec -- pytest -x --no-cov $test_targets 2>&1)"
test_status=$?

if [[ $test_status -eq 0 ]]; then
  pass_line="$(printf '%s\n' "$test_out" | grep -E '^=+ .*passed' | tail -1 || true)"
  echo "verify-tests: pytest OK${pass_line:+ — $pass_line}"
  exit 0
fi

cat >&2 <<EOF
verify-tests: pytest failed for tests scoped to changed Python files.

Changed files:
$changed_py

Test targets:
$test_targets

Pytest output:
$test_out

IMPORTANT: do NOT modify test files (test_*.py, tests/, bin/tests/) to make
this pass. Fix the production code in the changed files instead.
EOF
exit 2
