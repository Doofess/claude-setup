#!/bin/bash
# PreToolUse hook (matcher: Bash). Blocks destructive git commands so the user runs them deliberately.
# Adapted from mattpocock/skills git-guardrails-claude-code; jq-free so it runs on a bare Git Bash.

INPUT=$(cat)

# Pull tool_input.command out of the JSON without jq. Handles escaped quotes inside the command.
COMMAND=$(printf '%s' "$INPUT" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(\([^"\\]\|\\.\)*\)".*/\1/p' | head -1)

DANGEROUS_PATTERNS=(
  "git push"
  "git reset --hard"
  "git clean -fd"
  "git clean -f"
  "git branch -D"
  "git checkout \."
  "git restore \."
  "push --force"
  "reset --hard"
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if printf '%s' "$COMMAND" | grep -qE "$pattern"; then
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user runs this themselves; ask them to." >&2
    exit 2
  fi
done

exit 0
