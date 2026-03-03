# Roadmap

## Status

- Phase 1: Semantische Langzeit-Erinnerung -> umgesetzt.
- Phase 2: Safety-Gated Runtime-Self-Modification -> umgesetzt.
- Phase 3: Daemon-Selbstläuferbetrieb -> umgesetzt.
- Phase 4: Task-Core + LLM-Task-Funnel mit Human-Gate -> umgesetzt (Foundation).
- Phase 5: Queue-Execution fuer `queued` Tasks -> umgesetzt (Basis-Worker).
- Phase 6: Worker-Routing ACC/NIMCF/KIdieKIruft -> umgesetzt (Adapter-Level).
- Phase 7: KIdieKIruft Live-Dispatch mit Safety-Gates -> umgesetzt (opt-in).
- Phase 8: KIdieKIruft Review-Sync zurueck in ACC -> umgesetzt.
- Phase 9: Task-Orchestrierung v2 -> umgesetzt (Dependencies, Retry, Worker-Scoring, Rework-Follow-up).
- Phase 10: Policy-Lernlogik v2 -> umgesetzt (datengetriebene Kandidatenwahl + gekoppelte Parameter-Aenderungen).
- Phase 11: Service-Haertung v2 -> umgesetzt (Daemon-Lock, strukturierte Logs, Health-Endpoint mit graceful fallback).
- Phase 12: Erweiterte Safety v1 -> umgesetzt (Self-Mod-Budget, Mode-Policies, Rollback-Alerting).

## Nächste Ausbaustufen

1. Erweiterte Safety
- Safety-Policies auf Task-Ebene pro Modus (z. B. maximale Parallelitaet/IO-Rechte je Worker).
- Eskalationspfad fuer kritische Policy-Verletzungen (Freeze + verpflichtendes Human-Review).

2. Qualität der Kognition
- Besseres Retrieval-Ranking (ANN/FAISS).
- Hypothesenbewertung mit robusteren Signalen.

3. Produktionsbetrieb
- Optionaler Restart-Manager (systemd/supervisor).
- Dashboards/Alerts auf Basis strukturierter Logs und Task-Metriken.
