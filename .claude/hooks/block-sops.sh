#!/usr/bin/env bash
# PreToolUse hook for Edit|Write — blocks edits to SOPS-encrypted files.
# Reads JSON from stdin, extracts tool_input.file_path, exits 2 if it matches a
# protected pattern. Exit code 2 stops the tool call and surfaces the message
# to Claude on stderr.

set -euo pipefail

input="$(cat)"
file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')"

[[ -z "$file_path" ]] && exit 0

base="${file_path##*/}"
# Note: */ansible/group_vars/*.sops.yaml is already covered by the *.sops.yaml
# arm above (shellcheck SC2222) — keep the broader patterns and let them win.
case "$file_path" in
  *.sops.yaml|*.sops.yml|*.enc.yaml|*.enc.yml)
    blocked=1 ;;
  */k8s/apps/*/secret.yaml|*/k8s/apps/*/secret.yml)
    blocked=1 ;;
  */k8s/apps/*/secrets/*)
    blocked=1 ;;
  *)
    blocked=0 ;;
esac

if [[ "$base" == "secret.yaml" || "$base" == "secret.yml" ]]; then
  case "$file_path" in
    */k8s/apps/*) blocked=1 ;;
  esac
fi

if [[ "$blocked" -eq 1 ]]; then
  cat >&2 <<EOF
Blocked: $file_path is SOPS-encrypted. Editing it directly will corrupt the
ciphertext and leak secrets in plaintext on disk. Decrypt with
\`sops -d\` first if a change is genuinely required, then re-encrypt.
EOF
  exit 2
fi

exit 0
