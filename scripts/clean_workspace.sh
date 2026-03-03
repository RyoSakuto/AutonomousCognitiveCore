#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STAMP="$(date -u +%Y-%m-%d)_clean_workspace"
ARCHIVE_DIR=".archive/${STAMP}"
mkdir -p "$ARCHIVE_DIR"

archive_if_exists() {
  local src="$1"
  local dst="$2"
  if [ -e "$src" ]; then
    mkdir -p "$(dirname "$dst")"
    mv "$src" "$dst"
  fi
}

archive_if_exists "data/acc.db" "${ARCHIVE_DIR}/data/acc.db"
archive_if_exists "KIdieKIruft/orchestrator/runs" "${ARCHIVE_DIR}/KIdieKIruft/orchestrator/runs"
archive_if_exists "KIdieKIruft/dist" "${ARCHIVE_DIR}/KIdieKIruft/dist"
archive_if_exists "KIdieKIruft/archive" "${ARCHIVE_DIR}/KIdieKIruft/archive"
archive_if_exists "nimcf/outbox" "${ARCHIVE_DIR}/nimcf/outbox"
archive_if_exists "nimcf/archive" "${ARCHIVE_DIR}/nimcf/archive"

mkdir -p data KIdieKIruft/orchestrator nimcf/outbox nimcf/archive
cat > KIdieKIruft/orchestrator/queue.json <<'JSON'
{
  "tasks": [],
  "history": []
}
JSON

find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +

echo "Workspace cleaned. Archive: ${ARCHIVE_DIR}"
