# Vertical Slice Spielpaket

Dieses Paket enthaelt den lauffaehigen CLI-Prototype des Spiels als eigenstaendigen Ordner.

## Version

- Aktueller Stand: `0.1.0`
- Paketversion: `VERSION` (im Spielpaketordner)
- Hinweis: Die uebergeordnete Projektversionsdatei liegt im Repo-Root unter `VERSION`.

## Spielidee

Du steuerst eine Spielfigur auf einem Raster (je nach Layout z. B. 5x5 oder 6x5).
Ziel ist es, 3 Energiezellen zu sammeln, danach die Extraktion zu aktivieren und den Extraktionspunkt lebend zu erreichen.
Nach jedem gueltigen Spielerzug zieht ein KI-Gegner (`G`) deterministisch per Manhattan-Chase nach.

## Steuerung

- `W`: nach oben bewegen
- `A`: nach links bewegen
- `S`: nach unten bewegen
- `D`: nach rechts bewegen
- `R`: Kampagne direkt neu starten (ohne Prozess-Neustart)
- `Q`: Mission abbrechen (Lose)

## Layouts und Difficulty-Kurve

Es gibt mehrere Layouts:

- `classic` (Standard)
- `corridor`
- `crossfire`

Standard-Kampagne (zentral definiert in `game/vertical_slice.py` als `CAMPAIGN_LEVELS`):
- `classic` -> `corridor` -> `crossfire`
- Nach einem Win startet das naechste Level automatisch.
- Schwierigkeit steigt datengetrieben pro Level:

| Level | Layout | starting_hp | turn_limit | hazard_density | hazard_count | enemy_turns_per_round | route_cutoff_weight | chase_weight |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | classic | 3 | 16 | low | 2 | 1 | 0 | 1 |
| 2 | corridor | 10 | 14 | normal | 4 | 2 | 2 | 1 |
| 3 | crossfire | 13 | 13 | high | 4 | 2 | 4 | 1 |

Score-Balancing wird beim Start aus der externen, versionierten JSON-Datei geladen:

- Pfad: `game/score_balance_profiles.json`
- Schema-Version: Feld `version` (aktuell `1`)
- Profile: `profiles.L1`, `profiles.L2`, `profiles.L3`
- Runtime-Bindung:
  - `SCORE_BALANCE_PROFILES` wird aus der JSON-Datei gebaut
  - `CAMPAIGN_LEVELS[*].score_balance` bindet das Profil explizit an jedes Kampagnenlevel
  - `GameConfig.score_balance` bleibt Runtime-Quelle fuer alle Score-Berechnungen

Validierung und Fallback:

- Fehlende oder ungueltige Felder erzeugen klare Validierungsfehler (inkl. Feldpfad)
- Bei Fehlern faellt das Spiel auf interne Fallback-Werte zurueck, damit der Start nicht blockiert wird
- Die Warnung wird im Event-Log mit Tag `[CONFIG]` angezeigt

Formel fuer den Run-Score:
- pro Zug: `turn_reward`
- pro Energiezelle: `energy_cell_reward`
- bei Aktivierung der Extraktion: `extraction_activation_reward`
- bei Schaden: Abzug ueber `hazard_damage_penalty` bzw. `enemy_collision_penalty`
- bei Level-Win: `level_win_base_reward + hp * level_win_hp_bonus + turns_left * level_win_turn_bonus`

| Level | turn_reward | energy_cell_reward | extraction_activation_reward | hazard_damage_penalty | enemy_collision_penalty | level_win_base_reward | level_win_hp_bonus | level_win_turn_bonus |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L1 (classic) | 12 | 120 | 160 | 24 | 36 | 220 | 42 | 22 |
| L2 (corridor) | 10 | 130 | 185 | 30 | 44 | 270 | 38 | 18 |
| L3 (crossfire) | 8 | 145 | 210 | 36 | 52 | 320 | 34 | 15 |

Beispiel-Format von `game/score_balance_profiles.json`:

```json
{
  "version": 1,
  "profiles": {
    "L1": {
      "turn_reward": 12,
      "energy_cell_reward": 120,
      "extraction_activation_reward": 160,
      "hazard_damage_penalty": 24,
      "enemy_collision_penalty": 36,
      "level_win_base_reward": 220,
      "level_win_hp_bonus": 42,
      "level_win_turn_bonus": 22
    },
    "L2": {
      "turn_reward": 10,
      "energy_cell_reward": 130,
      "extraction_activation_reward": 185,
      "hazard_damage_penalty": 30,
      "enemy_collision_penalty": 44,
      "level_win_base_reward": 270,
      "level_win_hp_bonus": 38,
      "level_win_turn_bonus": 18
    },
    "L3": {
      "turn_reward": 8,
      "energy_cell_reward": 145,
      "extraction_activation_reward": 210,
      "hazard_damage_penalty": 36,
      "enemy_collision_penalty": 52,
      "level_win_base_reward": 320,
      "level_win_hp_bonus": 34,
      "level_win_turn_bonus": 15
    }
  }
}
```

Anpassungsworkflow (ohne Code-Deployment):

1. `game/score_balance_profiles.json` im Repo anpassen.
2. Pflichtfelder pro Profil (`L1` bis `L3`) vollstaendig beibehalten.
3. `./run_tests.sh` ausfuehren.
4. JSON-Datei committen/deployen; beim naechsten Start wird automatisch neu geladen.

`--hazard-density` ist weiterhin nutzbar:

- `low`
- `normal` (Standard)
- `high`

Verhalten:
- `normal`: nutzt die oben definierte Kurve pro Level.
- `low`/`high`: globaler Override fuer alle Level.
- Die Gegnerheuristik (`route_cutoff_weight` vs `chase_weight`) bleibt levelabhaengig, damit spaetere Level aggressiver auf Routen-Blockade reagieren.
- Regressionshinweis (TASK-025): Bei `route_cutoff_weight=0` nutzt L1 einen reinen Chase-Tie-Break ohne versteckte Key-Pressure-Priorisierung.

Tie-Breaking von `choose_enemy_step` (explizite Reihenfolge):
- L1 (`route_cutoff_weight=0`): `collision_priority -> weighted_pressure -> chase_distance -> index`
- L2/L3, normaler Zustand (`route_cutoff_weight>0` und `enemy_pos!=player_pos`):
  - route-dominant (`route_cutoff_weight > chase_weight`): `collision_priority -> weighted_pressure -> route_distance -> key_distance -> chase_distance -> extraction_distance -> index`
  - chase-dominant/equal (`route_cutoff_weight <= chase_weight`): `collision_priority -> weighted_pressure -> chase_distance -> key_distance -> route_distance -> extraction_distance -> index`
- L2/L3, Overlap-Zustand (`route_cutoff_weight>0` und `enemy_pos==player_pos`): `collision_priority` wird zu spaetem Tie-Break verschoben, damit Gewichtung (`route_cutoff/chase`) zuerst aufloest:
  - route-dominant: `weighted_pressure -> route_distance -> key_distance -> chase_distance -> extraction_distance -> collision_priority -> index`
  - chase-dominant/equal: `weighted_pressure -> chase_distance -> key_distance -> route_distance -> extraction_distance -> collision_priority -> index`
- Extraction aktiv (`extraction_active=True`, `route_cutoff_weight>0`):
  - normal: `collision_priority -> weighted_pressure -> route_distance -> chase_distance -> extraction_distance -> key_distance -> index`
  - im Overlap-Zustand: `weighted_pressure -> route_distance -> chase_distance -> extraction_distance -> key_distance -> collision_priority -> index`

Verfuegbare Layouts anzeigen:

```bash
python3 game/vertical_slice.py --list-layouts
```

## Symbole im Spielfeld

- `P`: Spieler
- `G`: KI-Gegner
- `C`: Energiezelle
- `X`: Extraktionspunkt (noch gesperrt)
- `E`: Extraktionspunkt (aktiv)
- `!`: Gefahrenfeld (verursacht Schaden)
- `.`: freies Feld

## Win-/Lose-Logik

Win:
- 3/3 Energiezellen gesammelt
- Extraktion aktiv
- Spieler erreicht `E` mit verbleibenden HP
- Bei Kampagnenstart auf `classic`: finaler Win erst nach dem letzten Level

Lose:
- HP fallen auf 0
- Kollision mit dem Gegner verursacht Schaden und kann dadurch Lose ausloesen
- Zuglimit laeuft ab
- manueller Abbruch mit `Q`

## Balancing und Zielpfade (pro Layout mit Kampagnen-Defaultwerten)

Die folgenden Sequenzen starten jeweils vom Spawnpunkt des Layouts und sind reproduzierbar mit den gezeigten Befehlen (`W/A/S/D`).
Die angegebenen Laufwerte entsprechen dem aktuellen Report (`scripts/report_route_balance.py`) mit den jeweiligen Kampagnen-Defaults (`L1` bis `L3`).

### `classic`

Balancing-Notiz: Kurzestes Tutorial-Layout; klare Kernschleife mit moderatem Risiko durch drei Gefahrenfelder.

- Win-Route: `W D S D D D A A S S S D D`
- Lose-Fall (HP auf 0): `W W W W W W`
- Laufwerte (L1-Defaults): `hazard-density low`, `hazard_count 2`, Win `status=win, hp=2, turns_left=3, score=1022`; Lose `status=lose, hp=0, turns_left=10, score=0`
- Erwartete Score-Spannen (Regression): Win `920-1040`, Lose `0-40`

### `corridor`

Balancing-Notiz: Enger Korridor mit hohem Positionsdruck; Win-Pfad ist kurz, aber fuehrt nahe an mehreren Gefahren vorbei.

- Win-Route: `D W W D D W D W D`
- Lose-Fall (HP auf 0): `W D D W S A D`
- Laufwerte (L2-Defaults): `hazard-density normal`, `hazard_count 4`, Win `status=win, hp=2, turns_left=5, score=777`; Lose `status=lose, hp=0, turns_left=7, score=0`
- Erwartete Score-Spannen (Regression): Win `730-830`, Lose `0-40`

### `crossfire`

Balancing-Notiz: Sicherer Erfolg verlangt bewusstes Umspielen der zentralen Gefahren; dafuer ist der optimale Win-Pfad laenger.

- Win-Route: `W W A A D D D D W A A W W`
- Lose-Fall (HP auf 0): `D W W W W W S W S`
- Laufwerte (L3-Defaults): `hazard-density high`, `hazard_count 4`, Win `status=win, hp=1, turns_left=0, score=590`; Lose `status=lose, hp=0, turns_left=4, score=0`
- Erwartete Score-Spannen (Regression): Win `540-640`, Lose `0-40`

## HUD und Event-Log

Die CLI-Ausgabe ist in drei Bereiche aufgeteilt:

- `HUD`: zeigt Kampagnenstand (`Level x/y`), Gegnerintensitaet (Zuege pro Spielerzug), laufenden `Score`, persistenten `Best-Run`, HP, verbleibende Zuege, Fortschritt (gesammelte Energiezellen) und Extraktionsstatus
- `KARTE`: zeigt das 5x5-Spielfeld mit allen Symbolen
- `EVENT`: zeigt die letzte Aktion als konsistente Meldung mit Tags wie `[AKTION]`, `[GEFAHR]`, `[GEGNER]`, `[MISSION]`

Nach Missionsende kann mit `R` sofort die Kampagne neu gestartet werden, ohne das Spiel neu zu starten.
Der Endscreen zeigt `ERGEBNIS`, `SCORE` und `BEST-RUN`.

Best-Run wird lokal in `meta_progression.json` (im Paketordner) gespeichert. Fehlende oder korrupte Save-Dateien werden beim Start automatisch toleriert und mit Defaultwerten weitergefuehrt.

## Spiel starten

Im Ordner `spielpaket_vertical_slice`:

```bash
./start_game.sh
```

### Start-Menue (Standard)

Beim normalen Start erscheint vor der Mission ein Text-Menue:

1. `Layout waehlen`
2. `Hazard-Dichte waehlen`
3. `Kampagnenmodus starten`
4. `Tests ausfuehren` (startet `./run_tests.sh` und kehrt ins Menue zurueck)
5. `Info anzeigen` (inkl. Test-Hinweis)
`Q` beendet den Start ohne Missionsbeginn

Damit sind Layout und Dichte ohne CLI-Flags konfigurierbar.

### Start mit expliziten CLI-Optionen

```bash
./start_game.sh --layout corridor --hazard-density high
```

### Menue-Modus steuern

```bash
python3 game/vertical_slice.py --menu auto   # Default, nur mit TTY
python3 game/vertical_slice.py --menu on     # Menue immer zeigen
python3 game/vertical_slice.py --menu off    # Menue ueberspringen
```

Alternativ direkt:

```bash
python3 game/vertical_slice.py
```

Direkt mit Optionen:

```bash
python3 game/vertical_slice.py --layout crossfire --hazard-density low
```

Optional mit explizitem Save-File:

```bash
python3 game/vertical_slice.py --save-file /tmp/meta_progression.json
```

## Tests ausfuehren

```bash
./run_tests.sh
```

## Route-Balance-Report (CI)

Fuer die automatisierte Regression der relevanten Win-/Lose-Routen:

```bash
python3 scripts/report_route_balance.py --output route_balance_report.json
```

Der JSON-Report enthaelt:

- pro Route den Endstatus (`actual_status`) und den Score (`score`)
- pro Layout/Level die Istwerte `min_score`/`max_score` getrennt fuer `win` und `lose`

CI-Verhalten:

- Standard: Exit-Code `0` nach erfolgreicher Report-Erzeugung
- Optional strikt: `python3 scripts/report_route_balance.py --output route_balance_report.json --strict`
  - Exit-Code `1`, wenn mindestens eine Route bei Status/Score von der Spezifikation abweicht

## Release-Checkliste (kurz)

Vor einem neuen Release sollten mindestens diese Checks gruen sein:

1. `./run_tests.sh`
2. `python3 scripts/report_route_balance.py --output route_balance_report.json --strict`
3. `../scripts/build_release.sh`

Empfohlen zusaetzlich:

- manueller Smoke-Test ueber `./start_game.sh` (Start-Menue, Kampagnenstart, 1-2 Zuege)
- `meta_progression.json` bei Bedarf zuruecksetzen, wenn ein cleanes Demo-Startbild gewuenscht ist

## Enthaltene Dateien

- `game/vertical_slice.py`: Spiellogik + CLI
- `game/score_balance_profiles.json`: versionierte Score-Balance-Profile (`L1` bis `L3`)
- `tests/test_vertical_slice.py`: Unittests
- `docs/game_blueprint.md`: Design- und Scope-Blueprint
- `CHANGELOG_SHORT.md`: kompakter Aenderungsverlauf fuer Releases
