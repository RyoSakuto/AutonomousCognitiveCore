#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <prompt_file>" >&2
  exit 2
fi

PROMPT_FILE="$1"
if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Prompt file not found: $PROMPT_FILE" >&2
  exit 2
fi

# Allow overriding the target directory if needed.
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
PROMPT="$(cat "$PROMPT_FILE")"

# Prefer modern GPT CLI semantics. In non-interactive shells `gpt` may exist
# only as alias (`npx @openai/codex`), so we fall back to direct npx usage.
WORKER_BIN="${WORKER_BIN:-gpt}"
CMD_BASE=()
if [[ "$WORKER_BIN" == "gpt" ]]; then
  if command -v gpt >/dev/null 2>&1; then
    CMD_BASE=("gpt")
  elif command -v codex >/dev/null 2>&1; then
    CMD_BASE=("codex")
  elif command -v npx >/dev/null 2>&1; then
    CMD_BASE=("npx" "-y" "@openai/codex")
  else
    echo "Worker CLI not found: gpt (no codex/npx fallback available)" >&2
    exit 127
  fi
else
  if command -v "$WORKER_BIN" >/dev/null 2>&1; then
    CMD_BASE=("$WORKER_BIN")
  elif [[ "$WORKER_BIN" != "codex" ]] && command -v codex >/dev/null 2>&1; then
    CMD_BASE=("codex")
  else
    echo "Worker CLI not found: $WORKER_BIN (and no codex fallback available)" >&2
    exit 127
  fi
fi

CMD=("${CMD_BASE[@]}" exec --full-auto --skip-git-repo-check --cd "$PROJECT_DIR")
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CMD+=(--model "$CODEX_MODEL")
fi

"${CMD[@]}" "$PROMPT"
