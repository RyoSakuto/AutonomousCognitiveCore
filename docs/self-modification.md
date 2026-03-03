# Safety-Gated Self-Modification

## Ziel

Kleine Laufzeitanpassungen zulassen, ohne unkontrollierte Eskalation.

## Workflow

1. Proposal-Erzeugung
- Basierend auf Heuristiken (z. B. Idle-Serien, Unsicherheits-Trends, Exploration-Defizit).
- Kandidaten werden datengetrieben priorisiert:
- Historie aus `self_mod_proposals` (approved/rejected/rolled_back + avg simulation score) fliesst in die Auswahl ein.

2. Gate-Prüfung
- Nur freigegebene Parameter.
- Parametergrenzen.
- Maximale Delta-Größe pro Schritt.
- Mode-Policy pro Betriebsmodus (`discovery|balanced|guarded|production`) inkl. Allow/Deny-Filter.
- Budget-Policy: maximale Anzahl `approved` Proposals pro Fenster.

3. Simulationsscore
- Einfache interne Nutzenabschätzung.
- Nicht-positive Scores werden abgelehnt.

4. Apply
- Approved Proposal aktualisiert `runtime_params`.
- `policy_updated` Episode wird geschrieben.
- Gekoppelte Updates sind moeglich (Primary + Coupled Proposal im selben Zyklus).
- Beispiel: `memory_retrieval_k` hoch -> `memory_min_score` leicht runter.

5. Post-Check / Rollback
- Nach `self_mod_rollback_window` Zyklen wird Effekt geprüft.
- Bei Regression (`avg_uncertainty` über Margin) Rollback auf alten Wert.
- Bei gehaeuften Rollbacks erzeugt ACC automatisch ein Warning-Alert-Event.

## Gekoppelte Parameter (aktuell)

- `memory_retrieval_k` -> `memory_min_score`
- `exploration_factor` -> `novelty_threshold` oder `uncertainty_threshold`
- `uncertainty_threshold` -> `conflict_threshold`

## Aktuell steuerbare Parameter

- `uncertainty_threshold`
- `conflict_threshold`
- `novelty_threshold`
- `exploration_factor`
- `memory_retrieval_k`
- `memory_min_score`

## Sicherheitscharakter

- Keine Codeänderungen.
- Nur Werte innerhalb enger Bandbreiten.
- Jede Entscheidung ist in Proposal- und Audit-Tabellen nachvollziehbar.
- Coupled-Proposals laufen durch denselben Gate- und Simulationspfad wie Primary-Proposals.
- Budget- und Policy-Blockaden werden als `rejected` Proposal + Audit + Agent-Event protokolliert.
