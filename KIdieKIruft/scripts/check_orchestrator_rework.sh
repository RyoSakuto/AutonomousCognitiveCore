#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

pushd "$TMP_DIR" >/dev/null

python3 "$REPO_ROOT/orchestrator.py" init >/dev/null
python3 "$REPO_ROOT/orchestrator.py" task add \
  --title "Smoke Task Rework" \
  --description "Negativen Worker-Pfad pruefen" \
  --acceptance "Task wird auf rework gesetzt" >/dev/null

export WORKER_CMD='python3 -c "import sys; print(\"ERROR: simulated worker failure\"); sys.exit(1)"'
set +e
python3 "$REPO_ROOT/orchestrator.py" dispatch --task-id TASK-001 >/dev/null
dispatch_rc=$?
set -e

if [[ "$dispatch_rc" -eq 0 ]]; then
  echo "Expected dispatch to fail for rework smoke-check, got exit-code 0." >&2
  exit 1
fi

python3 - <<'PY'
import json
from pathlib import Path

queue = json.loads(Path("orchestrator/queue.json").read_text(encoding="utf-8"))
task = queue["tasks"][0]

assert task["status"] == "rework", f"Unexpected status: {task['status']}"
assert task["attempts"] == 1, f"Unexpected attempts: {task['attempts']}"
assert task["last_run"], "Missing last_run"

events = [entry["type"] for entry in queue["history"]]
for expected in ("task_added", "worker_failed"):
    assert expected in events, f"Missing history event: {expected}"

run_dir = Path(task["last_run"])
for artifact in ("worker_prompt.md", "stdout.log", "stderr.log", "meta.json"):
    path = run_dir / artifact
    assert path.exists(), f"Missing artifact: {path}"

meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))

assert meta["effective_success"] is False, "Expected effective_success to be false"
assert meta["returncode"] == 1, f"Unexpected returncode: {meta['returncode']}"
assert meta["failure_reasons"], "Expected failure_reasons in meta.json"
assert any("Worker meldet Fehler:" in reason for reason in meta["failure_reasons"]), (
    f"Unexpected failure_reasons: {meta['failure_reasons']}"
)

print("Smoke check passed: Worker failure -> rework.")
PY

popd >/dev/null
