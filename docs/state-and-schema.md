# Persistenter Zustand und Schema

## Datenbank

- Standardpfad: `data/acc.db`
- Engine: SQLite
- Schema-Initialisierung: automatisch über `ACCDatabase.ensure_schema()`

## Kern-Tabellen

- `self_model`: Selbstmodell-Key/Value
- `goals`: interne Ziele inkl. Status
- `metrics`: Unsicherheit/Konflikt/Neuheit/Spannung pro Zyklus
- `episodes`: Ereignislog pro Zyklus
- `hypotheses`: Hypothesen + Entscheidung
- `memory_embeddings`: semantischer Langzeitspeicher
- `dialog_turns`: persistente Session-Dialoghistorie (`user` / `assistant`)
- `runs`: Run-Statistik

## Task-Core-Tabellen (Foundation)

- `tasks`
- Generische Aufgabenverwaltung fuer interne/externe Work Items
- Enthaelt `task_key`, `status`, `priority`, `owner`, `context_json`, Ergebnis-/Fehlerfelder

- `task_dependencies`
- Dependency-Kanten zwischen Tasks (`task_id` -> `depends_on_task_id`, Typ `hard|soft`)

- `task_runs`
- Ausfuehrungsversuche pro Task (Worker, Input/Output, Logs, Metriken, Dauer)

- `task_reviews`
- Bewertungs-/Review-Layer pro Task/Run (z. B. `approved`, `rework`, `rejected`)

- `agent_events`
- Ein einheitliches Event-Log fuer Orchestrierungsereignisse mit Severity und Payload

## Wichtige Task-Statuswerte

- `idea`
- `creative`
- `queued`
- `running`
- `done`
- `failed`
- `blocked`
- `rework`

Hinweis:
- Neue Statuswerte koennen spaeter ohne DB-Migration eingefuehrt werden, da aktuell kein hartes SQL-`CHECK` auf `tasks.status` gesetzt ist.

## Self-Mod-Tabellen

- `runtime_params`
- Aktive, dynamische Runtime-Policy-Werte

- `self_mod_proposals`
- Proposal-Historie mit Risiko, Simulationsscore, Status
- Statuswerte: `approved`, `rejected`, `rolled_back`

- `self_mod_audit`
- Audit-Trail zu Gate-Entscheidungen, Apply/Post-Check/Rollback

## Wichtige Episode-Typen

- `goal_generated`
- `memory_retrieved`
- `hypothesis_evaluated`
- `branch_created`
- `goal_resolved`
- `policy_updated`
- `external_goal_received`
- `external_response_generated`
- `idle`
