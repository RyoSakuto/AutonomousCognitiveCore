# ACC Dokumentation

Stand: 2026-03-03

Diese Dokumentation beschreibt den aktuellen Implementierungsstand des `Autonomous Cognitive Core (ACC)`.

## Inhalte

- `architecture.md`: Systemarchitektur und Modulverantwortung
- `runtime-loop.md`: Exakter Ablauf des autonomen Denkzyklus
- `state-and-schema.md`: Persistenter Zustand und SQLite-Schema
- `semantic-memory.md`: Embeddings, Retrieval und Auditierbarkeit
- `self-modification.md`: Safety-Gates, Proposal-Workflow, Rollback
- `daemon-mode.md`: Dauerbetrieb, Tick-Modell, Stop-Verhalten
- Interaktionsmodi in `runbook.md`: `--ask`, `--chat`, `--session-id`
- `configuration.md`: Alle Laufzeitparameter inkl. ENV/CLI
- `llm-integration.md`: Lokale LLM/Embedding-Anbindung mit Fallback
- `task-core.md`: Einheitliches Task-Core-Modell (Tasks, Runs, Reviews, Events)
- Goal-to-Plan ist in `task-core.md`, `architecture.md` und `runbook.md` beschrieben
- `runbook.md`: Betrieb, Checks, Troubleshooting
- `validation-and-metrics.md`: KPI und Validierung
- `roadmap.md`: Nächste Ausbauphasen
- `original-blueprint.md`: Urspruengliches Konzept (Legacy)
- `repo-bootstrap.md`: GitHub-Start und Push-Workflow

## Doku-Ziele

- Reproduzierbarkeit: Jeder Lauf ist nachvollziehbar.
- Auditierbarkeit: Interne Entscheidungen und Änderungen sind in DB-Logs sichtbar.
- Änderbarkeit: Erweiterungen ohne Architekturbruch.
