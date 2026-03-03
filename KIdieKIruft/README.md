# Projektstatus: Spielpaket + Orchestrator

Dieses Repository ist fuer neue Task-Reihen vorbereitet.
Das bisherige Ergebnis wurde als eigenstaendiges Spielpaket abgelegt.

## Aktuelle Version

- Release-Version: `0.1.0`
- Versionsquelle: `VERSION`

## Spielpaket

Der lauffaehige Vertical Slice liegt in:

- `spielpaket_vertical_slice/`

Dort findest du:

- `README.md` mit Spielbeschreibung, Steuerung, Balancing-Notizen pro Layout und reproduzierbaren Win-/Lose-Routen
- `start_game.sh` zum direkten Start
- `run_tests.sh` fuer die Spieltests
- `scripts/report_route_balance.py` fuer den JSON-Report der regressionsrelevanten Win-/Lose-Routen (CI-tauglich)
- `game/` mit der Spiellogik
- `tests/` mit Unittests
- `docs/game_blueprint.md` als Design-Blueprint

Schnellstart:

```bash
cd spielpaket_vertical_slice
./start_game.sh
```

## Release-Paket erstellen

Fuer eine einfache Weitergabe kann ein reproduzierbares `tar.gz`-Paket gebaut werden:

```bash
./scripts/build_release.sh
```

Ergebnis:

- Artefakt unter `dist/spielpaket_vertical_slice-release.tar.gz`
- Enthalten: `README.md`, `VERSION`, `CHANGELOG_SHORT.md`, `start_game.sh`, `run_tests.sh`, `game/`, `docs/`

## Orchestrator (aktueller Zustand + Resume)

Snapshot vom `2026-02-14`:

- `29` Tasks im aktuellen Zyklus
- `29` auf `approved`
- keine offenen Tasks (`ready/rework/in_progress/submitted = 0`)

Den Live-Stand (nach jedem Neustart) pruefst du mit:

```bash
python3 orchestrator.py status
```

### Fortsetzen nach CLI-Neustart

Wenn die CLI neu gestartet wurde, kann der aktuelle Stand sofort wieder aufgenommen werden:

```bash
python3 orchestrator.py status
```

Das Kommando zeigt:

- Task-Anzahl und Statusverteilung
- naechste dispatchbare Task
- zuletzt verwendetes Run-Verzeichnis inkl. Log-Dateien
- konkrete Resume-Befehle

Empfohlener Resume-Flow:

```bash
export WORKER_CMD='./scripts/worker_codex.sh {prompt_file}'
export WORKER_BIN='gpt'
export WORKER_TIMEOUT_SECONDS=900
export ORCH_FOLLOWUP_POLICY='none'
python3 orchestrator.py autopilot --max-tasks 1
```

Hinweise:
- `scripts/worker_codex.sh` behandelt `WORKER_BIN='gpt'` robust auch ohne Shell-Alias und faellt auf lokale `codex`-Binarys zurueck.
- `WORKER_TIMEOUT_SECONDS=0` deaktiviert den Timeout (nicht empfohlen).
- `ORCH_FOLLOWUP_POLICY` steuert neue Folge-Tasks aus Worker-Artefakten:
  - `none` (Standard): keine neuen Folge-Tasks (Sicherungsmodus)
  - `all`: alle vorgeschlagenen Folge-Tasks werden importiert
  - `bugfix_only`: nur Follow-ups mit Bugfix-/Regression-Fokus werden importiert

Neue Tasks anlegen:

```bash
python3 orchestrator.py task add --title "..." --description "..."
python3 orchestrator.py task list
```

Wenn du nur manuell reviewen willst:

```bash
python3 orchestrator.py task list
python3 orchestrator.py review --task-id TASK-XYZ --decision approve --notes "..."
```

### Prefix-Freigaben fuer Worker-Starts

Damit Worker-Laeufe ohne staendige Rueckfragen gestartet werden koennen, sind folgende Prefixe freigegeben:

- `python3 orchestrator.py autopilot`
- `python3 orchestrator.py dispatch`
- `./scripts/worker_codex.sh`

Typischer Start:

```bash
WORKER_CMD='./scripts/worker_codex.sh {prompt_file}' WORKER_BIN='gpt' python3 orchestrator.py autopilot --task-id TASK-001 --max-tasks 1
```

Direkter Worker-Aufruf:

```bash
./scripts/worker_codex.sh orchestrator/runs/TASK-001/<RUN_ID>/worker_prompt.md
```

## Release-Readiness und Sicherung

Vollstaendiger Check- und Freigabestatus:

- `docs/release_readiness.md`

Automatischer Vorab-Check vor Release:

```bash
./scripts/check_release_readiness.sh
```

Der Check fuehrt aus:

- Spieltests (`./spielpaket_vertical_slice/run_tests.sh`)
- strikten Route-Report (`--strict`)
- aktuellen Orchestrator-Status
- Release-Build inkl. SHA256-Ausgabe (`./scripts/build_release.sh`)

## Archiv des letzten Task-Zyklus

Der vorige Arbeitsstand wurde archiviert unter:

- `archive/task_cycle_20260214/queue.json`
- `archive/task_cycle_20260214/runs/`

Damit bleibt der alte Verlauf nachvollziehbar, ohne den neuen Zyklus zu blockieren.
