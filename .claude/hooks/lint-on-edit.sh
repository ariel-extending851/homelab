#!/usr/bin/env bash
# PostToolUse hook for Edit|Write — runs the right linter for the edited file.
# Always exits 0 (informational, never blocks). Output goes to stdout so Claude
# can read and act on it.

set -uo pipefail

input="$(cat)"
file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')"

[[ -z "$file_path" || ! -f "$file_path" ]] && exit 0

# Skip generated/state artifacts and SOPS files (block-sops.sh would have
# rejected them on PreToolUse, but defend in depth).
case "$file_path" in
  *.tfstate|*.tfstate.backup|*/.terraform/*|*.tfplan)
    exit 0 ;;
  *.sops.yaml|*.sops.yml|*.enc.yaml|*.enc.yml)
    exit 0 ;;
  */k8s/apps/*/secret.yaml|*/k8s/apps/*/secret.yml|*/k8s/apps/*/secrets/*)
    exit 0 ;;
esac

ext="${file_path##*.}"
out=""
status=0

run() {
  out="$("$@" 2>&1)" || status=$?
}

case "$file_path" in
  *.tf)
    if command -v mise >/dev/null 2>&1; then
      run mise exec -- terraform fmt -check -diff "$file_path"
    fi ;;
  */.github/workflows/*.yml|*/.github/workflows/*.yaml)
    if command -v mise >/dev/null 2>&1; then
      run mise exec -- actionlint "$file_path"
    fi ;;
  *.yml|*.yaml)
    if command -v mise >/dev/null 2>&1; then
      run mise exec -- yamllint "$file_path"
    fi ;;
  *.py)
    if command -v mise >/dev/null 2>&1; then
      run mise exec -- black --check --diff "$file_path"
    fi ;;
  *.sh|*.bash)
    if command -v mise >/dev/null 2>&1; then
      run mise exec -- shellcheck "$file_path"
    fi ;;
  *)
    exit 0 ;;
esac

if [[ $status -ne 0 && -n "$out" ]]; then
  echo "lint-on-edit: $file_path (.${ext}) reported issues:"
  echo "$out"
fi

# Always exit 0 — lint is informational, not a hard block.
exit 0
