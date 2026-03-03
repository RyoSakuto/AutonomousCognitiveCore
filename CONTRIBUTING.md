# Contributing

Danke fuers Mitbauen am `AutonomousCognitiveCore`.

## Kurzablauf

1. Fork oder Branch anlegen.
2. Aenderung klein und fokussiert halten.
3. Lokal pruefen:
   - `python3 -m compileall acc main.py`
   - `python3 main.py --cycles 1 --db-path /tmp/acc_contrib_check.db`
4. PR mit klarer Beschreibung erstellen.

## Commit-Stil

- Empfehlung: `type: kurze beschreibung`
- Beispiele:
  - `feat: add worker policy guard`
  - `fix: handle retry backoff edge case`
  - `docs: clarify runbook startup`

## PR-Qualitaet

- Problem und Loesung kurz erklaeren.
- Bei Verhaltensaenderung: Beispiel-CLI oder Output beilegen.
- Doku aktualisieren, wenn sich Bedienung/Config aendert.

## Scope-Regeln

- Keine destruktiven Git-Operationen in PRs.
- Keine geheimen Keys/Token committen.
- Runtime-Artefakte nicht einchecken (`.db`, `__pycache__`, Logs, Archive).
