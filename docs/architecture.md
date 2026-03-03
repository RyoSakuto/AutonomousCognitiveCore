# Architektur

## Überblick

ACC ist ein modularer, zustandsbehafteter Agent mit persistentem Speicher. Ein Orchestrator führt kontinuierliche oder begrenzte Denkzyklen aus.

## Kernmodule

- `main.py`
- CLI und Daemon-Steuerung.

- `acc/orchestrator.py`
- Führt den End-to-End-Denkzyklus aus.
- Nutzt Runtime-Policy (dynamisch anpassbar).
- Enthält Task-Funnel-Automation (`idea -> creative -> queued`) inkl. optionalem Human-Gate.
- Enthält Queue-Execution fuer `queued` Tasks (`acc.executor`) inkl. Run/Review/Event-Audit.
- Routing-Layer fuer mehrere Worker (`acc`, `nimcf`, `kidiekiruft`) mit dynamischem Worker-Scoring (Erfolg/Konfidenz/Fallback/Last).
- Enthaelt Dependency-Gate und Retry-Strategie pro Task (konfigurierbar ueber `context_json` + Defaults).
- Enthaelt Worker-Allow/Deny-Policies je `operating_mode` mit Policy-Override-Eventing.
- `kidiekiruft` kann kontrolliert im `dry-run` oder `live-dispatch` Modus laufen (Config-gesteuert).
- Enthält einen Sync-Pass fuer `blocked` KIdieKIruft-Tasks, der externe Reviews in ACC-Status ueberfuehrt und Artefakte nach ACC importiert.
- Externe Rework-Notizen koennen Auto-Requeue + Follow-up-Erzeugung triggern.

- `acc/state.py`
- Persistenzzugriff auf Self-Model, Goals, Metrics, Episodes, Hypothesen, Runtime-Params, Self-Mod-Audit.
- Beinhaltet den Task-Core (`tasks`, `task_dependencies`, `task_runs`, `task_reviews`, `agent_events`) als orchestrierbare API-Schicht.

- `acc/self_modification.py`
- Safety-gesteuerte Laufzeitanpassung:
- Proposal-Erzeugung
- datengetriebene Kandidaten-Priorisierung aus Proposal-Historie
- Gate-Prüfung
- Simulationsscore
- Apply
- gekoppelte Parameterupdates (Primary + Coupled)
- Budget-Limits pro Zyklusfenster
- Mode-Allow/Deny-Policies fuer aenderbare Parameter
- Post-Check + Rollback
- Rollback-Alerting bei gehaeuften Ruecknahmen

- `acc/service_runtime.py`
- Service-Layer fuer Daemon-Betrieb:
- Single-Instance Lockfile
- Strukturierte JSONL-Logs
- Optionaler HTTP-Health-Endpoint (`/health`, `/healthz`)

- `acc/memory.py` + `acc/embedding.py`
- Semantisches Memory mit Similarity-Retrieval.

- `acc/goal_generator.py`
- Intrinsische Zielerzeugung anhand der Runtime-Policy-Schwellen.

- `acc/meta_cognition.py`
- Confidence und Commit/Explore-Entscheidung.

- `acc/exploration.py`
- Counterfactual Branching mit explorationsabhängiger Wahrscheinlichkeit.

## Datenfluss

1. Snapshot aus internem Zustand.
2. Goal-Generation über aktive Policy.
3. Memory-Retrieval als Kontext.
4. Hypothesengenerierung + Meta-Evaluation.
5. Branching bei Bedarf.
6. Safety-Layer evaluiert Policy-Anpassungen.
7. Änderungen werden auditiert und ggf. zurückgerollt.
8. Alles persistiert in SQLite.
