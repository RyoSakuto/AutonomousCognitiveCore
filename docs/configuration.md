# Konfiguration

## Priorität

1. Defaults in `ACCConfig`
2. INI-Dateien (`config/acc.ini`, `config/acc.local.ini` oder `--config`)
3. ENV (`ACC_*`)
4. CLI-Argumente

## INI-Dateien

- Repo-Vorlage: `config/acc.example.ini`
- Lokale private Dateien: `config/acc.ini` oder `config/acc.local.ini`
- Beide lokalen Dateien sind per `.gitignore` ausgeschlossen.
- Eigene Pfade koennen per `--config <pfad>` eingebunden werden.
- Wenn `--config` mehrfach gesetzt wird, ueberschreibt spaeteres frueheres.

Empfohlener Flow:

```bash
cp config/acc.example.ini config/acc.local.ini
```

Danach nur `config/acc.local.ini` fuer die eigene Maschine anpassen.

## Kernparameter

- `ACC_DB_PATH` / `--db-path`
- `--config <pfad>`
- `ACC_MAX_CYCLES` / `--cycles`
- `ACC_TICK_INTERVAL`
- `ACC_LLM_PROVIDER` / `--llm-provider`
- `ACC_LLM_MODEL` / `--llm-model`
- `ACC_LLM_ENDPOINT` / `--llm-endpoint`
- `ACC_LLM_TIMEOUT` / `--llm-timeout`
- `ACC_LLM_API_KEY` / `--llm-api-key`
- `ACC_LLM_AUTO_DISCOVER` / `--llm-auto-discover`
- `ACC_LLM_AUTO_LOAD` / `--llm-auto-load`
- `ACC_LLM_PREFER_LOADED` / `--llm-no-prefer-loaded`
- `ACC_LLM_LOAD_TIMEOUT` / `--llm-load-timeout`
- `ACC_LLM_SWITCH_BUDGET` / `--llm-switch-budget`
- `ACC_LLM_PLANNER_MODEL` / `--llm-planner-model`
- `ACC_LLM_REVIEWER_MODEL` / `--llm-reviewer-model`
- `ACC_LLM_CHAT_MODEL` / `--llm-chat-model`
- `--list-llm-models`
- `--load-llm-model <name>`

## Planning

- `--plan-goal`
- `--plan-default-status`
- `--plan-base-priority`
- `--session-id` (auch fuer Planner nutzbar)

## Trigger und Exploration

- `ACC_UNCERTAINTY_THRESHOLD`
- `ACC_CONFLICT_THRESHOLD`
- `ACC_NOVELTY_THRESHOLD`
- `ACC_EXPLORATION_FACTOR`
- `ACC_OPERATING_MODE` / `--operating-mode` (`discovery|balanced|guarded|production`)

## Memory

- `ACC_EMBEDDING_PROVIDER` / `--embedding-provider`
- `ACC_EMBEDDING_MODEL` / `--embedding-model`
- `ACC_EMBEDDING_ENDPOINT` / `--embedding-endpoint`
- `ACC_EMBEDDING_DIMENSIONS`
- `ACC_MEMORY_RETRIEVAL_K`
- `ACC_MEMORY_CANDIDATE_WINDOW`
- `ACC_MEMORY_MIN_SCORE`

## Self-Modification

- `ACC_SELF_MOD_ENABLED` / `--disable-self-mod`
- `ACC_SELF_MOD_MIN_CYCLES_BETWEEN_CHANGES`
- `ACC_SELF_MOD_ROLLBACK_WINDOW`
- `ACC_SELF_MOD_REGRESSION_MARGIN`
- `ACC_SELF_MOD_BUDGET_WINDOW_CYCLES` / `--self-mod-budget-window`
- `ACC_SELF_MOD_MAX_APPROVED_PER_WINDOW` / `--self-mod-max-approved`
- `ACC_SELF_MOD_ALLOW_PARAMS` / `--self-mod-allow-params`
- `ACC_SELF_MOD_DENY_PARAMS` / `--self-mod-deny-params`
- `ACC_SELF_MOD_ROLLBACK_ALERT_WINDOW` / `--self-mod-rollback-alert-window`
- `ACC_SELF_MOD_ROLLBACK_ALERT_THRESHOLD` / `--self-mod-rollback-alert-threshold`

## Daemon

- `ACC_DAEMON_INTERVAL_SEC` / `--daemon-interval`
- `ACC_DAEMON_CYCLES_PER_TICK` / `--daemon-cycles-per-tick`
- `--daemon`
- `--daemon-max-ticks`
- `ACC_SERVICE_LOCK_PATH` / `--daemon-lock-path`
- `ACC_STRUCTURED_LOGGING_ENABLED` / `--structured-logs`
- `ACC_STRUCTURED_LOG_PATH` / `--structured-log-path`
- `ACC_HEALTH_SERVER_ENABLED` / `--health-server`
- `ACC_HEALTH_SERVER_HOST` / `--health-host`
- `ACC_HEALTH_SERVER_PORT` / `--health-port`

## Task-Funnel

- `ACC_TASK_FUNNEL_ENABLED` / `--disable-task-funnel`
- `ACC_TASK_FUNNEL_BATCH_SIZE` / `--task-funnel-batch`
- `ACC_TASK_HUMAN_FEEDBACK_GATE` / `--task-human-gate`
- `--task-funnel-now` (einmaliger Transition-Pass)
- `ACC_TASK_EXECUTION_ENABLED` / `--disable-task-execution`
- `ACC_TASK_EXECUTION_BATCH_SIZE` / `--task-exec-batch`
- `ACC_TASK_DEPENDENCY_ENFORCEMENT`
- `ACC_TASK_RETRY_DEFAULT_MAX_RETRIES`
- `ACC_TASK_RETRY_DEFAULT_BACKOFF_SEC`
- `ACC_TASK_EXTERNAL_REWORK_AUTO_REQUEUE`
- `ACC_WORKER_STATS_WINDOW_RUNS`
- `ACC_WORKER_ALLOWLIST` / `--worker-allowlist`
- `ACC_WORKER_DENYLIST` / `--worker-denylist`
- `--execute-queue-now` (einmaliger Execution-Pass fuer `queued` Tasks)
- `--sync-kidiekiruft-now` (einmaliger Sync-Pass fuer `blocked` KIdieKIruft-Tasks)
- `--list-tasks [status|all]`
- `--approve-task <id|task_key>`
- `--reject-task <id|task_key>`
- `--feedback "..."` (fuer Human-Entscheidungen)
- `--create-task "beschreibung"` + `--task-title/--task-status/--task-priority/--task-source`
- `--task-worker acc|nimcf|kidiekiruft` (Routing-Hinweis beim Erstellen)
- `--depends-on <id|task_key>` (mehrfach moeglich) + `--dependency-type hard|soft`
- `--task-max-retries <n>` + `--task-retry-backoff <sec>` + `--task-retry-on failed,rework`

## KIdieKIruft Routing

- `ACC_KIDIEKIRUFT_ROOT` / `--kidiekiruft-root`
- `ACC_KIDIEKIRUFT_LIVE_DISPATCH_ENABLED` / `--kidiekiruft-live-dispatch`
- `ACC_KIDIEKIRUFT_WORKER_CMD` / `--kidiekiruft-worker-cmd`
- `ACC_KIDIEKIRUFT_WORKER_BIN` / `--kidiekiruft-worker-bin`
- `ACC_KIDIEKIRUFT_WORKER_TIMEOUT_SEC` / `--kidiekiruft-timeout`

## Beispiel

```bash
ACC_LLM_PROVIDER=ollama \
ACC_EMBEDDING_PROVIDER=ollama \
ACC_DAEMON_CYCLES_PER_TICK=3 \
python3 main.py --daemon --daemon-interval 2
```

```bash
ACC_LLM_PROVIDER=openai_compatible \
ACC_LLM_ENDPOINT=http://192.168.0.56:1234 \
ACC_LLM_MODEL=mistralai/ministral-3-14b-reasoning \
ACC_LLM_PLANNER_MODEL=mistralai/ministral-3-14b-reasoning \
ACC_LLM_REVIEWER_MODEL=openai/gpt-oss-20b \
ACC_LLM_CHAT_MODEL=openai/gpt-oss-20b \
ACC_LLM_AUTO_DISCOVER=true \
ACC_LLM_AUTO_LOAD=false \
ACC_LLM_SWITCH_BUDGET=1 \
python3 main.py --ask "Erstelle mir einen kleinen Plan und erklaere ihn kurz."
```
