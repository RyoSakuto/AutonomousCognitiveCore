# Validierung und Metriken

## Kern-KPI

- `autonomous_tasks`
- `avg_uncertainty`
- Goal-Status-Verteilung
- Entscheidungsmix (`commit`/`explore`/`branch`)
- `idle`-Anteil
- Memory-Retrieval-Events

## Safety-KPI

- Anzahl `approved` / `rejected` / `rolled_back` Proposals
- Häufigkeit von `policy_updated`
- Post-Check-Ergebnisse im `self_mod_audit`

## Daemon-KPI

- Zykluskontinuität (monotone `cycle`-Werte)
- Stabilität über mehrere Ticks (`runs`-Serie)

## Mindestkriterien

- Erfolgreicher Run-Eintrag in `runs`
- Persistierte Hypothesen + Memory-Einträge
- Keine ungated Parameteränderungen (alles über Proposal/Audit)
- Daemon-Smoketest läuft mit mehreren Ticks durch
