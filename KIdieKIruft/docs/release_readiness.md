# Release Readiness (Snapshot 2026-02-14)

## Ziel

Diese Datei dokumentiert den verifizierten Stand vor einem Release des aktuellen Spielpakets.

## Version

- Zielrelease: `0.1.0`
- Versionsquelle: `VERSION`

## Gepruefte Artefakte

- Spielpaket: `spielpaket_vertical_slice/`
- Route-Report: `spielpaket_vertical_slice/route_balance_report.json`
- Release-Archiv: `dist/spielpaket_vertical_slice-release.tar.gz`
- Orchestrator-Zustand: `orchestrator/queue.json`, `orchestrator/runs/`

## Durchgefuehrte Checks

### 1) Volltest Spiel

- Kommando: `./spielpaket_vertical_slice/run_tests.sh`
- Ergebnis: `49 tests`, `OK`

### 2) Route-Regression (strikt)

- Kommando:
  - `./spielpaket_vertical_slice/scripts/report_route_balance.py --strict --output spielpaket_vertical_slice/route_balance_report.json`
- Ergebnis:
  - `all_routes_passed: true`
  - `route_count: 6`
  - `classic win/lose: 1022 / 0`
  - `corridor win/lose: 777 / 0`
  - `crossfire win/lose: 590 / 0`

### 3) Build-Artefakt

- Kommando: `./scripts/build_release.sh`
- Ergebnis:
  - Datei: `dist/spielpaket_vertical_slice-release.tar.gz`
  - SHA256: `a35ec21c1f4d64a5530ab6ad311477a07e3f91b9907ec89f47060988a4a7da73`

### 4) Orchestrator-Status

- Kommando: `python3 orchestrator.py status`
- Ergebnis:
  - `approved: 29`
  - `ready/rework/in_progress/submitted: 0`
  - keine dispatchbaren Tasks

## Spielfaehigkeit (dokumentiert)

Die Spielbarkeit ist ueber Tests und Reports abgesichert:

- Kampagne ist spielbar (`test_full_campaign_normal_is_playable`)
- L1 bleibt gewinnbar (`test_campaign_l1_remains_winnable_with_deterministic_bfs_route`)
- deterministische Win-/Lose-Routen bleiben reproduzierbar (`test_000` / `test_001`)
- Start-Menue, Neustart und Save-Fallback sind getestet

## Offene Release-Gates

Aktuell kein technischer Blocker aus den automatisierten Checks.

Empfohlen vor externer Veroeffentlichung:

- mindestens ein kurzer manueller Smoke-Test (`./spielpaket_vertical_slice/start_game.sh`)
- Versions-/Tag-Entscheidung fuer das Artefakt
- falls gewuenscht: changelogseitige Zusammenfassung der letzten Task-Welle

## Wiederholbarer Preflight

Fuer den naechsten Release-Kandidaten:

```bash
./scripts/check_release_readiness.sh
```
