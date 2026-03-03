#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

pushd "$TMP_DIR" >/dev/null

python3 "$REPO_ROOT/orchestrator.py" init >/dev/null
python3 "$REPO_ROOT/orchestrator.py" task add \
  --title "Smoke Task" \
  --description "Plan->Dispatch->Review E2E pruefen" \
  --acceptance "README.md existiert" >/dev/null

export WORKER_CMD='python3 -c "print(\"smoke worker ok\")"'
python3 "$REPO_ROOT/orchestrator.py" dispatch --task-id TASK-001 >/dev/null
python3 "$REPO_ROOT/orchestrator.py" review --task-id TASK-001 --decision approve --notes "Smoke-Check" >/dev/null

python3 - <<'PY'
import json
from pathlib import Path

queue = json.loads(Path("orchestrator/queue.json").read_text(encoding="utf-8"))
task = queue["tasks"][0]

assert task["status"] == "approved", f"Unexpected status: {task['status']}"
assert task["attempts"] == 1, f"Unexpected attempts: {task['attempts']}"
assert task["last_run"], "Missing last_run"

events = [entry["type"] for entry in queue["history"]]
for expected in ("task_added", "worker_submitted", "reviewed"):
    assert expected in events, f"Missing history event: {expected}"

run_dir = Path(task["last_run"])
for artifact in ("worker_prompt.md", "stdout.log", "stderr.log", "meta.json"):
    path = run_dir / artifact
    assert path.exists(), f"Missing artifact: {path}"

print("Smoke check passed: Plan->Dispatch->Review.")
PY

popd >/dev/null
