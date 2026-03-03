# Plan-Dispatch-Review Loop

Diese Doku beschreibt den minimalen QS-Ablauf fuer den Orchestrator und wie er reproduzierbar geprueft wird.

## Ziel

Sicherstellen, dass der Kernprozess stabil bleibt:
1. Plan (Task in Queue)
2. Dispatch (Task an Worker)
3. Review (Entscheidung + Statuswechsel)

## Minimaler Ablauf

```bash
python3 orchestrator.py init
python3 orchestrator.py task add \
  --title "Beispiel" \
  --description "Loop pruefen" \
  --acceptance "README.md existiert"
export WORKER_CMD='./scripts/worker_codex.sh {prompt_file}'
python3 orchestrator.py dispatch --task-id TASK-001
python3 orchestrator.py review --task-id TASK-001 --decision approve --notes "ok"
```

Erwartung:
- Task wechselt von `ready` nach `submitted` und danach nach `approved`.
- Run-Artefakte liegen unter `orchestrator/runs/<TASK-ID>/<RUN-ID>/`.

## Automatisierte Smoke-Checks

```bash
./scripts/check_orchestrator_loop.sh
./scripts/check_orchestrator_rework.sh
```

Die Checks isolieren sich in einem Temp-Verzeichnis und validieren:
- Positiver Pfad: Queue-History (`task_added`, `worker_submitted`, `reviewed`) und Task-Felder (`status=approved`, `attempts=1`, `last_run`)
- Negativer Pfad: Queue-History (`task_added`, `worker_failed`) und Task-Felder (`status=rework`, `attempts=1`, `last_run`)
- Run-Artefakte (`worker_prompt.md`, `stdout.log`, `stderr.log`, `meta.json`) inklusive `failure_reasons` im negativen Pfad

## Troubleshooting

- `WORKER_CMD is not set`
  Ursache: Kein Worker-Kommando konfiguriert.
  Fix: `export WORKER_CMD='...'` setzen.

- `Worker-Authentifizierung fehlgeschlagen` oder `unauthorized`
  Ursache: CLI-Session abgelaufen oder fehlende Berechtigung.
  Fix: Neu anmelden (`gpt login`/`codex login`) und Zugriff pruefen.

- `Konfiguriertes Modell ist nicht verfuegbar oder nicht freigeschaltet`
  Ursache: Falscher Modellname oder fehlender Access.
  Fix: Modell wechseln (`CODEX_MODEL`) oder Access freischalten.

- Task geht auf `rework` trotz Returncode `0`
  Ursache: Fatal-Muster in Logs erkannt.
  Fix: `meta.json`, `stdout.log`, `stderr.log` im Run-Ordner auswerten.

- `No dispatchable task found.`
  Ursache: Keine Task in Status `ready`/`rework`.
  Fix: Task-Status in `python3 orchestrator.py task list` pruefen.
