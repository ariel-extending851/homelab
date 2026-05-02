#!/usr/bin/env bash
# PreToolUse hook — defense-in-depth against reads of sensitive secret material
# (SOPS age keys, SSH private keys, AWS credentials). Inspects the relevant
# fields of tool_input depending on the tool: command (Bash), file_path (Read),
# pattern/path (Grep), pattern (Glob). Exit 2 stops the tool call.

set -euo pipefail

input="$(cat)"

extract() { printf '%s' "$input" | jq -r "$1 // empty"; }

cmd="$(extract '.tool_input.command')"
file_path="$(extract '.tool_input.file_path')"
grep_path="$(extract '.tool_input.path')"
pattern="$(extract '.tool_input.pattern')"

haystack="$cmd $file_path $grep_path $pattern"

# Sensitive paths to protect anywhere they appear in the tool input.
if [[ "$haystack" =~ (^|[^a-zA-Z0-9_.-])(~|/home/[^/[:space:]]+|\$HOME)/\.config/sops($|/) ]] \
   || [[ "$haystack" =~ (^|[^a-zA-Z0-9_.-])(~|/home/[^/[:space:]]+|\$HOME)/\.ssh($|/) ]] \
   || [[ "$haystack" =~ (^|[^a-zA-Z0-9_.-])(~|/home/[^/[:space:]]+|\$HOME)/\.aws/credentials($|[^a-zA-Z]) ]] \
   || [[ "$haystack" =~ /\.config/sops/age/keys\.txt ]]; then
  cat >&2 <<'EOF'
Blocked: access to sensitive secret material is not allowed.
Protected paths: ~/.config/sops/**, ~/.ssh/**, ~/.aws/credentials.
These contain private keys (age, SSH) or cloud credentials and must never be
read, listed, or piped through any tool. If you need to operate on encrypted
files, use `sops -d <file>` against the ciphertext in the repo — never touch
the key material itself.
EOF
  exit 2
fi

exit 0
