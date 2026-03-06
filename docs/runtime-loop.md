# Autonomer Denkzyklus

## Ablauf pro Zyklus

1. `observe_internal_state(cycle)`
- Erfasst `uncertainty`, `conflict`, `novelty`, `tension`.

2. Task-Funnel (neu)
- `idea -> creative -> queued` ueber LLM-gestuetzte Transitions.
- Optionales Human-Gate: bei Queue-Reife geht Task auf `blocked` statt direkt `queued`.

Zwischenschritt davor moeglich:
- Ein externes Ziel kann zuerst in einen Task-Plan zerlegt werden (`--plan-goal`), bevor der normale Funnel/Execution-Lauf startet.

3. Externer Sync (neu)
- `blocked` Tasks mit KIdieKIruft-Mapping werden gegen externen Review-Status synchronisiert.
- Mapping: `approved -> done`, `rework -> queued` (Default Auto-Requeue) oder `rework`.
- Bei Rework koennen Follow-up-Tasks automatisch erzeugt werden.
- Externe Artefakte (`meta`, `followups`, Log-Excerpts) werden in `context_json` importiert.

4. Queue-Execution (neu)
- `queued` Tasks werden vor Claim auf Dependencies und Retry-Backoff geprueft.
- Worker wird dynamisch ueber Performance/Last gewaehlt (mit Hint-Boost).
- Ausfuehrung: `running -> done|rework|failed|blocked` oder `running -> queued` (Retry-Scheduling).
- Jeder Lauf schreibt `task_runs`, `task_reviews`, `agent_events`.

5. Intrinsische Goal-Generierung
- Trigger über aktuelle Runtime-Policy-Schwellen.

6. Aktive Goal-Auswahl
- Top-3 offene Goals.
- Kein Goal: `idle`-Episode.

7. Semantisches Retrieval
- Query aus Goal + aktuellem Zustand.
- Top-k Memory-Treffer über Similarity.

8. Hypothese erzeugen
- Prompt enthält Goal, Zustand, Self-Model, Memory-Kontext.

9. Meta-Evaluation
- Confidence + Entscheidung (`commit` / `explore`).

10. Commit/Resolve/Branch
- Commit aktualisiert Strategie.
- Resolve bei hoher Confidence.
- Explore erzeugt Counterfactual-Branch.

11. Safety-Layer
- Optional Proposal für Runtime-Policy.
- Gate + Simulationsscore entscheiden Apply/Reject.
- Budget-Limit pro Zyklusfenster kann Proposals blockieren.
- Mode-Policies (Allow/Deny) begrenzen aenderbare Parameter.
- Nach Monitoringfenster: Keep oder Rollback.
- Bei Rollback-Haeufung: automatisches Alert-Event.

12. Persistenz
- Metrics, Episodes, Hypothesen, Memory, Proposals, Audit, Runs.
- Zusaetzlich: Tasks, Task-Runs, Reviews, Agent-Events.

## Zyklusnummern

Zyklen sind global fortlaufend über mehrere `run()`-Aufrufe und Daemon-Ticks hinweg.
