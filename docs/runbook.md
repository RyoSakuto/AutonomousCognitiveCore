# Runbook

## Einmaliger Run

```bash
python3 main.py --cycles 12
```

## Run mit strenger Safety-Policy

```bash
python3 main.py --cycles 12 \
  --operating-mode production \
  --worker-allowlist acc \
  --self-mod-max-approved 1 \
  --self-mod-budget-window 24
```

## Einzelfrage (natuerliche Sprache)

```bash
python3 main.py --ask "Was ist mein naechster Schritt fuer Stabilitaet?" --cycles 6 --session-id demo
```

## Chat-Modus

```bash
python3 main.py --chat --session-id demo --cycles 4
```

## Daemon-Run

```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5
```

## Gehaerteter Daemon-Run

```bash
python3 main.py \
  --daemon \
  --daemon-cycles-per-tick 4 \
  --daemon-interval 5 \
  --daemon-lock-path data/acc_daemon.lock \
  --structured-logs \
  --structured-log-path data/acc_service.log.jsonl \
  --health-server \
  --health-host 127.0.0.1 \
  --health-port 8765
```

## Kurzer Daemon-Smoketest

```bash
python3 main.py --daemon --daemon-max-ticks 3 --daemon-interval 0.2 --daemon-cycles-per-tick 2
```

## Workspace Cleanup (sauberer Neustart)

```bash
./scripts/clean_workspace.sh
```

## Task erstellen (z. B. Idee)

```bash
python3 main.py --create-task "Wir sollten unsere Review-Pipeline robuster machen." --task-status idea --task-priority 0.8
```

## Ziel automatisch in Plan zerlegen

```bash
python3 main.py \
  --plan-goal "Baue eine Verbesserung fuer das semantische Gedaechtnis mit Tests und Dokumentation" \
  --session-id planner-demo
```

Hinweis:
- ACC erzeugt mehrere Tasks inkl. Dependencies.
- Standardmaessig startet der erste Task eher in `creative`, Folge-Tasks oft in `queued`.

## Task mit Dependency + Retry

```bash
python3 main.py --create-task "Basis-Task zuerst erledigen" --task-status queued --task-title "Basis"
python3 main.py --create-task "Folgetask nach Basis" \
  --task-status queued \
  --depends-on TASK-00001 \
  --dependency-type hard \
  --task-max-retries 2 \
  --task-retry-backoff 5 \
  --task-retry-on failed,rework
```

## Task-Funnel einmal ausfuehren

```bash
python3 main.py --task-funnel-now --task-funnel-batch 3
```

## Queue-Execution einmal ausfuehren

```bash
python3 main.py --execute-queue-now --task-exec-batch 2
```

## Worker gezielt waehlen

```bash
python3 main.py --create-task "Kontextanalyse ueber NIMCF" --task-status queued --task-worker nimcf
python3 main.py --create-task "Plane kleine Umsetzungspakete" --task-status queued --task-worker llm_planner
python3 main.py --create-task "Reviewe ein Zwischenergebnis" --task-status queued --task-worker llm_reviewer
python3 main.py --create-task "Delegations-Vorbereitung" --task-status queued --task-worker kidiekiruft
python3 main.py --execute-queue-now --task-exec-batch 4
```

## LM Studio / lokales LLM (empfohlen bei langsamen Modellen)

```bash
python3 main.py \
  --llm-provider openai_compatible \
  --llm-endpoint http://192.168.0.56:1234 \
  --llm-model mistralai/ministral-3-14b-reasoning \
  --llm-timeout 180 \
  --plan-goal "Erstelle einen kleinen Plan zur Verbesserung der Doku mit anschliessendem Review"
```

## KIdieKIruft live dispatch (optional)

```bash
python3 main.py \
  --create-task "Delegiere diesen Task an KIdieKIruft live" \
  --task-status queued \
  --task-worker kidiekiruft

python3 main.py \
  --execute-queue-now \
  --kidiekiruft-live-dispatch \
  --kidiekiruft-worker-cmd "./scripts/worker_codex.sh {prompt_file}" \
  --kidiekiruft-worker-bin gpt \
  --kidiekiruft-timeout 900
```

## KIdieKIruft Sync manuell ausfuehren

```bash
python3 main.py --sync-kidiekiruft-now
```

Hinweis:
- Im normalen `run`/`daemon` ist Queue-Execution standardmaessig aktiv.
- Abschalten fuer Diagnosen: `--disable-task-execution`
- Bei externer `kidiekiruft`-Rework-Entscheidung wird (Default) auto-requeued und ein Follow-up-Task erzeugt.

## Human-Gate Freigaben

```bash
python3 main.py --list-tasks blocked
python3 main.py --approve-task TASK-00012 --feedback "Freigegeben zur Umsetzung."
python3 main.py --reject-task TASK-00012 --feedback "Bitte zunaechst Akzeptanzkriterien schaerfen."
```

Hinweis:
- Feedback wird nach Approval/Rejection automatisch durch ACC interpretiert.
- Beispiel: Bei "kann ich eine genauere Beschreibung haben?" praezisiert ACC die Task-Beschreibung selbststaendig.

## Health-Check (DB)

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('data/acc.db')
conn.row_factory = sqlite3.Row
print('latest_run', dict(conn.execute("SELECT id,cycles,autonomous_tasks,round(avg_uncertainty,3) avg_u FROM runs ORDER BY id DESC LIMIT 1").fetchone()))
print('last_cycle', conn.execute("SELECT MAX(cycle) FROM metrics").fetchone()[0])
print('self_mod', [dict(r) for r in conn.execute("SELECT status,COUNT(*) c FROM self_mod_proposals GROUP BY status")])
print('memory', [dict(r) for r in conn.execute("SELECT source_kind,COUNT(*) c FROM memory_embeddings GROUP BY source_kind")])
print('dialog_turns', [dict(r) for r in conn.execute("SELECT session_id,COUNT(*) c FROM dialog_turns GROUP BY session_id")])
print('tasks_by_status', [dict(r) for r in conn.execute("SELECT status,COUNT(*) c FROM tasks GROUP BY status")])
print('task_runs', [dict(r) for r in conn.execute("SELECT status,COUNT(*) c FROM task_runs GROUP BY status")])
print('agent_events', conn.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0])
PY
```

## Troubleshooting

- Zu passiv (`idle` hoch): Trigger-Schwellen leicht senken.
- Zu viele Branches: `ACC_EXPLORATION_FACTOR` reduzieren.
- Kein Self-Mod: `ACC_SELF_MOD_ENABLED` prüfen und genug Zyklen laufen lassen.
- Unstabile Self-Mod-Änderungen: Rollback-Margin/Fenster strenger setzen.
- Queue steht auf `queued`, aber nichts startet: Dependencies (`task_dependencies`) und Retry-Backoff (`next_retry_at`) prüfen.
- Health-Server startet nicht: Port-Rechte/Sandbox prüfen; ACC laeuft trotzdem weiter (Warnung + Log-Event).
