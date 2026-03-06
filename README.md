# Autonomous Cognitive Core (ACC)

MVP++ implementation of an autonomous cognitive loop based on the blueprint.

![ACC CI](https://github.com/RyoSakuto/AutonomousCognitiveCore/actions/workflows/acc-ci.yml/badge.svg)

## Documentation

- Full technical documentation index: `docs/README.md`
- Original concept blueprint (legacy): `docs/original-blueprint.md`
- Repo setup guide (GitHub): `docs/repo-bootstrap.md`

## Repository Health

- License: `MIT` (`LICENSE`)
- Changelog: `CHANGELOG.md`
- Contribution guide: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`
- Code of conduct: `CODE_OF_CONDUCT.md`

## What is implemented

- Persistent internal state (`SQLite`)
- Intrinsic goal generation from uncertainty, conflict and novelty
- Meta-cognitive evaluation (`confidence`, `weaknesses`, `commit/explore`)
- Controlled exploration via counterfactual branching
- Autonomous cycle execution without external prompt
- Semantic long-term memory (embeddings + retrieval in prompt context)
- Safety-gated runtime self-modification (proposal -> gate -> simulation -> apply/rollback)
- Daemon mode for continuous operation
- Natural-language interaction layer (`--ask`, `--chat`) with session memory
- Optional local LLM/embedding hooks (`Ollama` or OpenAI-compatible server) with safe fallback
- Unified task-core foundation (`tasks`, `task_runs`, `task_reviews`, `agent_events`) for multi-agent orchestration
- Automatic task funnel (`idea -> creative -> queued`) with optional human feedback gate (`blocked`)
- Automatic queue execution (`queued -> running -> done|rework|failed`) with task-run audit trail
- Task dependencies (`task_dependencies`) + dependency-aware execution gate
- Retry strategy per task via context (`max_retries`, `retry_backoff_sec`, `retry_on_statuses`)
- Dynamic worker selection (ACC/NIMCF/KIdieKIruft) based on recent performance and runtime load
- Deep KIdieKIruft sync import (run meta/log excerpts/followups) with optional auto-requeue and rework follow-up generation
- Service hardening for daemon mode (single-instance lock, structured JSONL logs, optional health endpoint)
- Extended safety controls (operating modes, worker allow/deny policies, self-mod budget limits, rollback alerting)
- Goal-to-plan layer: natural-language goal -> task graph with dependencies

## Project structure

- `main.py`: CLI entrypoint (+ daemon mode)
- `acc/config.py`: runtime configuration
- `acc/db.py`: schema and DB connection
- `acc/state.py`: persistent state and observations
- Task-Core API in `acc/state.py`: task queueing, claiming, run artifacts, reviews, events
- `acc/goal_generator.py`: intrinsic goal creation
- `acc/meta_cognition.py`: evaluation and decision logic
- `acc/exploration.py`: branching strategy
- `acc/embedding.py`: embedding providers (`hash` / `ollama`)
- `acc/memory.py`: semantic memory store and retrieval
- `dialog_turns` in DB: session-based user/assistant conversation memory
- `acc/self_modification.py`: safety-gated runtime policy adaptation
- `acc/llm.py`: local LLM adapter (`none` / `ollama` / `openai_compatible`)
- `acc/project_planner.py`: goal-to-plan conversion and planner task generation
- `acc/orchestrator.py`: end-to-end autonomous loop

## Run once

```bash
python3 main.py --cycles 12
```

## Clean workspace for a fresh start

```bash
./scripts/clean_workspace.sh
```

## Ask ACC in natural language

```bash
python3 main.py --ask "Analysiere meine Unsicherheit im Projekt und gib mir den naechsten Schritt." --cycles 6
```

## Create and funnel tasks

```bash
python3 main.py --create-task "Neue Ziele fuer das System brainstormen" --task-status idea --task-priority 0.85
python3 main.py --task-funnel-now --task-funnel-batch 3
python3 main.py --execute-queue-now --task-exec-batch 2
python3 main.py --list-tasks all
```

Create a plan from one larger goal:

```bash
python3 main.py \
  --plan-goal "Baue eine Verbesserung fuer das semantische Gedaechtnis mit Tests und Dokumentation" \
  --session-id planner-demo
```

Route task execution to a specific worker:

```bash
python3 main.py --create-task "Memory-Analyse fuer Kontextabgleich" --task-status queued --task-worker nimcf
python3 main.py --create-task "Plane kleine Umsetzungsstufen" --task-status queued --task-worker llm_planner
python3 main.py --create-task "Reviewe ein Zwischenergebnis" --task-status queued --task-worker llm_reviewer
python3 main.py --create-task "Delegations-Skizze fuer externe Worker" --task-status queued --task-worker kidiekiruft
python3 main.py --execute-queue-now --task-exec-batch 4
```

Run with strict safety profile:

```bash
python3 main.py --cycles 8 \
  --operating-mode production \
  --worker-allowlist acc \
  --self-mod-max-approved 1 \
  --self-mod-budget-window 24
```

Create task dependencies and retry policy:

```bash
python3 main.py --create-task "Base task" --task-status queued --task-title Base
python3 main.py --create-task "Follow task" --task-status queued \
  --depends-on TASK-00001 \
  --dependency-type hard \
  --task-max-retries 2 \
  --task-retry-backoff 5 \
  --task-retry-on failed,rework
```

Optional live dispatch for `kidiekiruft` (default is safe dry-run):

```bash
python3 main.py --execute-queue-now \
  --kidiekiruft-live-dispatch \
  --kidiekiruft-worker-cmd "./scripts/worker_codex.sh {prompt_file}" \
  --kidiekiruft-worker-bin gpt \
  --kidiekiruft-timeout 900
```

Manual sync for blocked `kidiekiruft` tasks:

```bash
python3 main.py --sync-kidiekiruft-now
```

With human gate:

```bash
python3 main.py --task-funnel-now --task-human-gate
python3 main.py --list-tasks blocked
python3 main.py --approve-task TASK-00001 --feedback "Freigabe durch Human."
```

ACC interpretiert das Feedback danach automatisch und kann z. B. die Task-Beschreibung eigenstaendig praezisieren.

## Interactive chat mode

```bash
python3 main.py --chat --session-id team-alpha --cycles 4
```

## Run as daemon

```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5
```

Hardened daemon run:

```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5 \
  --daemon-lock-path data/acc_daemon.lock \
  --structured-logs --structured-log-path data/acc_service.log.jsonl \
  --health-server --health-host 127.0.0.1 --health-port 8765
```

For a bounded test run:

```bash
python3 main.py --daemon --daemon-max-ticks 3 --daemon-interval 0.2 --daemon-cycles-per-tick 2
```

## Optional local providers (Ollama)

```bash
python3 main.py --cycles 12 --llm-provider ollama --llm-model llama3.1
```

```bash
python3 main.py --cycles 12 --embedding-provider ollama --embedding-model nomic-embed-text
```

## Optional OpenAI-compatible local server

Example for your server/model:

```bash
python3 main.py --cycles 12 \
  --llm-provider openai_compatible \
  --llm-endpoint http://192.168.0.56:1234 \
  --llm-timeout 90 \
  --llm-model mistralai/ministral-3-14b-reasoning
```

For slower local reasoning models, `--llm-timeout 120` to `180` is recommended.

If your server requires a key:

```bash
python3 main.py --cycles 12 \
  --llm-provider openai_compatible \
  --llm-endpoint http://192.168.0.56:1234 \
  --llm-model mistralai/ministral-3-14b-reasoning \
  --llm-api-key YOUR_KEY
```

Optional endpoint overrides:

```bash
python3 main.py \
  --llm-provider ollama --llm-endpoint http://localhost:11434/api/generate \
  --embedding-provider ollama --embedding-endpoint http://localhost:11434/api/embeddings
```

If Ollama is unreachable, ACC falls back to deterministic heuristic behavior and continues.

## Useful checks

Inspect latest run summary without `sqlite3` CLI:

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect("data/acc.db")
for row in conn.execute("SELECT id,cycles,autonomous_tasks,round(avg_uncertainty,3) FROM runs ORDER BY id DESC LIMIT 1"):
    print(row)
PY
```
