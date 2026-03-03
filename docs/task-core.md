# Task Core

Stand: 2026-03-03

## Ziel

Der Task Core ist die gemeinsame Basis fuer ACC, NIMCF und KIdieKIruft:

- Aufgaben standardisiert speichern
- Aufgaben durch Worker claimen und ausfuehren
- Ausfuehrungen und Artefakte nachvollziehbar loggen
- Reviews und Agent-Events zentral dokumentieren

## Datenmodell

- `tasks`
- Primare Aufgabenobjekte (`task_key`, `status`, `priority`, `owner`, `context_json`)

- `task_runs`
- Ein Ausfuehrungsversuch zu einem Task inkl. I/O, Logs, Metriken, Dauer

- `task_dependencies`
- Abhaengigkeiten zwischen Tasks (`task_id` wartet auf `depends_on_task_id`, Typ `hard|soft`)

- `task_reviews`
- Qualitaetsentscheidung zu Task/Run (`reviewer`, `decision`, `score`, `feedback`)

- `agent_events`
- Allgemeines Event-Log mit `event_type`, `severity`, optionalem Bezug auf `cycle`, `task_id`, `run_id`

## Empfohlene Statuswerte

- `idea`: Rohidee, noch unscharf, muss konkretisiert werden
- `creative`: Brainstorm-/Explorationsphase fuer neue Loesungsansaetze
- `queued`: bereit zur Bearbeitung
- `running`: aktuell in Ausfuehrung
- `blocked`: wartet auf externe Klaerung/Abhaengigkeit
- `rework`: erneute Bearbeitung nach Review noetig
- `done`: erfolgreich abgeschlossen
- `failed`: Ausfuehrung fehlgeschlagen

Hinweis:
- Der Statuskatalog ist absichtlich erweiterbar. Da kein DB-`CHECK` aktiv ist, koennen neue Status spaeter eingefuehrt werden.
- API-seitig werden Statuswerte normalisiert (lowercase), damit `IDEA` und `idea` gleich behandelt werden.

## StateStore API (aktuell)

- `create_task(...)`
- `get_task(task_id)`
- `get_task_by_key(task_key)`
- `list_tasks(status=None, limit=20)`
- `claim_next_task(worker)`
- `update_task_status(task_id, status, result_summary=None, error_text=None)`
- `add_task_dependency(task_id, depends_on_task_id, dependency_type='hard')`
- `list_task_dependencies(task_id, include_status=False)`
- `list_unmet_task_dependencies(task_id)`
- `create_task_run(...)`
- `complete_task_run(...)`
- `list_task_runs(task_id, limit=12)`
- `count_task_runs(task_id, status=None)`
- `get_recent_task_runs(limit=120)`
- `add_task_review(...)`
- `list_task_reviews(task_id, limit=12)`
- `add_agent_event(...)`
- `list_agent_events(...)`

## Minimaler Ablauf

1. Task anlegen mit `create_task(...)`
2. Worker holt naechsten Task mit `claim_next_task(...)`
3. Run starten mit `create_task_run(...)`
4. Run beenden mit `complete_task_run(...)`
5. Review erfassen mit `add_task_review(...)`
6. Ereignisse schreiben mit `add_agent_event(...)`
7. Task finalisieren mit `update_task_status(..., status='done'|'failed')`

## Automatischer Funnel

ACC kann jetzt automatisch pro Zyklus:

1. `idea -> creative` (Idee wird in Brainstorm-Task ausgearbeitet)
2. `creative -> queued` (bei ausreichender Ausfuehrungsreife)
3. Optional mit Human-Gate:
- Bei Reife geht Task auf `blocked` und wartet auf manuelle Freigabe (`--approve-task`) oder Rueckgabe (`--reject-task`).

## Automatische Queue-Execution

ACC kann `queued` Tasks jetzt pro Zyklus selbst ausfuehren:

1. Claim: `queued -> running`
2. Execution-Run: Worker `acc.executor` erzeugt Ergebnis, Notes und optional Follow-up-Tasks
3. Dependency-Gate: `queued` Tasks mit offenen `hard`-Dependencies werden nicht gestartet
4. Retry-Policy: pro Task ueber `context_json` (`max_retries`, `retry_backoff_sec`, `retry_on_statuses`)
5. Abschluss: `done`, `rework`, `failed` oder `blocked`
6. Audit: Jeder Lauf wird in `task_runs`, `task_reviews`, `agent_events` protokolliert

Defaults:
- Queue-Execution ist standardmaessig aktiv.
- Batchgroesse pro Zyklus: `ACC_TASK_EXECUTION_BATCH_SIZE` (Default `1`).
- Retry-Defaults: `ACC_TASK_RETRY_DEFAULT_MAX_RETRIES=1`, `ACC_TASK_RETRY_DEFAULT_BACKOFF_SEC=0`.

## Worker-Routing (ACC / NIMCF / KIdieKIruft)

Routing-Reihenfolge:

1. Expliziter Kontext-Hinweis im Task (`context_json.worker` / `target_worker`)
2. Kandidatenliste (`context_json.worker_candidates`) + Source-Hints
3. Dynamische Auswahl ueber Worker-Score:
- Erfolgsquote, Konfidenz, Fallback-Rate, aktuelle Last (`running`)
- Hint-Boost fuer passende Quelle/Titel
4. Safety-Policy pro Betriebsmodus (`operating_mode`) + optionale Worker-Allow/Deny-Listen
5. Fallback auf `acc`

Aktueller Stand pro Worker:

- `acc`: interne Execution-Heuristik/LLM-Auswertung mit Follow-up-Unterstuetzung
- `nimcf`: direkter Aufruf von `nimcf` Coordinator-API (`run_task`)
- `kidiekiruft`: Delegation ueber KIdieKIruft-Orchestrator
- Default: `task add + dispatch --dry-run` (sicherer Scaffold)
- Optional live: `dispatch` ohne dry-run (nur mit `WORKER_CMD` aktivierbar)

Live-Status-Mapping (kidiekiruft -> ACC):

- `approved` -> `done`
- `rework` -> `queued` (Auto-Requeue aktiv) oder `rework` (wenn Auto-Requeue deaktiviert)
- `submitted` / `in_progress` / sonst -> `blocked` (wartet auf externen Review-Abschluss)

Sync:
- Automatisch in jedem ACC-Zyklus.
- Optional manuell: `python3 main.py --sync-kidiekiruft-now`.
- Artefakt-Import: `last_run`, `meta.json`, `followup_tasks.json`, Log-Excerpts werden in `context_json` gespiegelt.
- Externe Rework-Notiz erzeugt optional automatisch einen Follow-up-Task (`creative`) inkl. Dependency.

## Auto-Interpretation von Human-Feedback

Wenn bei `--approve-task` oder `--reject-task` ein Feedback-Text mitgegeben wird, verarbeitet ACC ihn automatisch:

1. Feedback wird semantisch eingeordnet (`acc.feedback_interpreter` Review + Event)
2. Bei Klaerungsbedarf wird die Task-Beschreibung automatisch praezisiert
3. Status bleibt konsistent:
- Bei Approval bleibt/ wird `queued`
- Bei Rework bleibt/ wird `creative`

## Abgrenzung

Der Task Core ist die Foundation, aber noch kein vollstaendiger Multi-Agent-Autopilot:

- Noch kein separates Human-Approval-Gate pro kritischem Task-Typ
- Noch kein globaler DAG-Scheduler mit Priorisierung ueber komplette Dependency-Graphen
