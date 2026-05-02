#!/usr/bin/env bash
# PreToolUse hook for Bash — blocks destructive commands and asks Claude to
# confirm with the user before retrying. Exit 2 surfaces the message and
# prevents execution.

set -euo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"

[[ -z "$cmd" ]] && exit 0

# Normalize whitespace for matching
norm="$(printf '%s' "$cmd" | tr -s '[:space:]' ' ')"

reason=""

if [[ "$norm" =~ git[[:space:]]+push[[:space:]]+.*(--force([^-]|$)|--force-with-lease|[[:space:]]-f([[:space:]]|$)) ]]; then
  reason="git force-push detected"
elif [[ "$norm" =~ git[[:space:]]+reset[[:space:]]+--hard ]]; then
  reason="git reset --hard discards uncommitted work"
elif [[ "$norm" =~ terraform[[:space:]]+(.*[[:space:]])?destroy ]]; then
  reason="terraform destroy will tear down infrastructure"
elif [[ "$norm" =~ kubectl[[:space:]]+delete[[:space:]]+(ns|namespace)[[:space:]]+ ]]; then
  reason="kubectl delete namespace deletes all workloads inside"
elif [[ "$norm" =~ rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*f?[[:space:]]+/[[:space:]]*$ || "$norm" =~ rm[[:space:]]+-[a-zA-Z]*f?r[a-zA-Z]*[[:space:]]+/[[:space:]]*$ ]]; then
  reason="rm -rf / would wipe the filesystem"
elif [[ "$norm" =~ git[[:space:]]+branch[[:space:]]+-D ]]; then
  reason="git branch -D force-deletes a branch"
elif [[ "$norm" =~ git[[:space:]]+clean[[:space:]]+-[a-zA-Z]*f ]]; then
  reason="git clean -f deletes untracked files"
fi

if [[ -n "$reason" ]]; then
  cat >&2 <<EOF
Destructive command blocked: $reason.
Command: $cmd

Ask the user for explicit confirmation before retrying. If they approve, you can
re-issue the same command and they will see the standard permission prompt.
EOF
  exit 2
fi

exit 0
