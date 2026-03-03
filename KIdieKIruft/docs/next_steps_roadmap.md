# Next Steps Roadmap: Level-Fortschritt und KI-Gegner

## Ausgangslage (Ist)
- Das Spiel ist aktuell ein einzelner Missionslauf pro Start (`GameState`, `GameConfig`, `run_cli`).
- Schwierigkeit entsteht bisher primaer aus Layout + Hazard-Dichte, nicht aus einer echten Level-Kette.
- Es gibt noch keinen Gegner mit eigenem Verhalten (nur statische Gefahrenfelder).

## Priorisierte Optionen

### 1) P1 - Kampagnenfluss mit echtem Level-Fortschritt (empfohlen als Start)
- Ziel: Nach `win` direkt ins naechste Level wechseln statt Programmende.
- Kernidee:
  - Neue `LevelDefinition`-Liste (z. B. `L1..L5`) als Reihenfolge im Code.
  - Nach erfolgreich abgeschlossener Mission: `current_level += 1`, neue Config laden, HP/Status klar definieren.
  - Endscreen erst nach letztem Level.
- Aufwand: M (ca. 0.5-1.0 Tag)
- Risiko: Niedrig (passt direkt auf vorhandene `run_cli`- und `build_game_config`-Struktur)
- Impact: Hoch (5/5) - schafft den benoetigten Fortschritts-Loop und motiviert Wiederholung.

### 2) P2 - Skalierende Schwierigkeit pro Level (datengetrieben)
- Ziel: Schwierigkeit steigt nachvollziehbar je Level.
- Kernidee:
  - Level-Parameter pro Stufe definieren: `turn_limit`, `hazard_density`, aktive Hazard-Anzahl, optional Start-HP.
  - Einfache Kurve: fruehe Level verzeihend, mittlere Level enger, spaete Level mit hoher Fehlertoleranz-Anforderung.
  - Schwierigkeit im HUD anzeigen (z. B. `Level 3/5 | Threat: 3`).
- Aufwand: M (ca. 0.5-1.0 Tag)
- Risiko: Mittel (Balancing kann Win/Lose-Routen brechen)
- Impact: Hoch (5/5) - macht den Fortschritt spielerisch spuerbar.

### 3) P3 - Machbarer KI-Gegner fuer CLI (deterministisch, regelbasiert)
- Ziel: Einen aktiven Gegner einfuehren, ohne Scope-Explosion.
- Kernidee:
  - Ein Gegner-Symbol (`G`) mit Runde-fuer-Runde-Bewegung nach Spielerzug.
  - Verhalten v1: Manhattan-Chase (greedy), blockiert durch Kartenrand; keine Pfadsuche noetig.
  - Trefferregel: Gegner auf Spielerposition verursacht 1 Schaden.
  - Skalierung pro Level: mehr Gegnerzuege pro Runde oder zusaetzlicher Gegner ab spaeter Stufe.
- Aufwand: M-L (ca. 1.0-1.5 Tage)
- Risiko: Mittel-Hoch (Reihenfolge von Ereignissen, Fairness, Testanpassungen)
- Impact: Hoch (4/5) - fuehlt sich nach echtem Gegnerdruck an.

### 4) P4 - Stabilitaetsnetz fuer neue Systeme (Simulation + Regressionstests)
- Ziel: Aenderungen an Progression/AI sicher iterieren.
- Kernidee:
  - Test-Helfer fuer mehrstufige Runs (Levelwechsel, Difficulty-Checks, AI-Kollisionen).
  - Mindestens 1 "goldener" Durchlauf pro Layout/Kampagne und 1 gezielter Lose-Fall pro Stufe.
- Aufwand: S-M (ca. 0.5 Tag)
- Risiko: Niedrig
- Impact: Mittel-Hoch (4/5) - reduziert Rework bei Balancing deutlich.

## Empfehlung
Empfohlene Reihenfolge: **P1 -> P2 -> P3**, mit P4 begleitend in jedem Schritt.

Begruendung:
- Ohne Level-Fortschritt bringt Difficulty-Skalierung nur begrenzten Nutzen.
- Difficulty-Kurve sollte vor KI eingefuehrt werden, damit klar ist, was "Level n" bedeutet.
- KI danach integrieren, damit Gegnerstaerke sauber in die bestehende Kurve eingebettet wird.

## Konkreter Umsetzungsplan (naechste 2-3 Tasks)

### Task A - Kampagnenmodus mit Level-Uebergang
- Ziel: Mehrere Level in einer Session spielen.
- Umsetzung:
  - Neue Kampagnenstruktur (`LEVEL_SEQUENCE`) und `CampaignState` einfuehren.
  - `run_cli` so erweitern, dass nach `win` entweder naechstes Level startet oder Kampagnen-Sieg endet.
  - HUD um `Level x/y` erweitern.
- Abnahme:
  - Win in Level 1 startet automatisch Level 2.
  - Nach letztem Level endet Session mit finalem Win.
  - Tests fuer Levelwechsel vorhanden.

### Task B - Difficulty-Kurve pro Level
- Ziel: Sichtbar steigende Schwierigkeit ueber die Kampagne.
- Umsetzung:
  - Pro Level Parametertabelle (Hazards, Turn-Limit, ggf. HP) zentral definieren.
  - Balancing-Regeln dokumentieren (`README` + kurze Notiz im Blueprint).
  - Bestehende Tests auf neue Grenzwerte aktualisieren/erweitern.
- Abnahme:
  - Spaetere Level haben objektiv hoehere Bedrohung als fruehe.
  - Mindestens ein reproduzierbarer Win-Pfad fuer fruehe/mittlere Stufe bleibt erhalten.
  - Test-Suite bleibt gruen.

### Task C - KI-Gegner v1 (regelbasiert)
- Ziel: Erster spielbarer Gegner ohne komplexe Algorithmen.
- Umsetzung:
  - Gegnerzustand in `GameState` integrieren.
  - Zugreihenfolge definieren: Spielerzug -> Missionslogik -> Gegnerzug -> Outcome.
  - Deterministische Regeln implementieren (greedy Chase, Kollisionsschaden, klare Event-Tags).
- Abnahme:
  - Gegner bewegt sich konsistent und nachvollziehbar je Runde.
  - Spieler kann durch Gegnerkontakt verlieren.
  - Neue Tests decken Bewegung/Kollision/Endzustand ab.

## Entscheidungsnotiz
Wenn nur **2 Tasks** im naechsten Sprint moeglich sind: zuerst **Task A + Task B**.
Task C startet danach mit stabiler Progressionsbasis und geringerem Balancing-Risiko.
