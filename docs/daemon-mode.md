# Daemon Mode

## Zweck

Kontinuierlicher Betrieb als Selbstläufer ohne manuelles Neustarten.

## Ausführung

```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5
```

## Service-Haertung (neu)

- Single-Instance Lock:
- `--daemon-lock-path /pfad/acc_daemon.lock`
- Zweiter Daemon mit gleichem Lock bricht sofort ab.

- Strukturierte Logs (JSONL):
- `--structured-logs --structured-log-path data/acc_service.log.jsonl`
- Enthalten Lifecycle-, Tick- und Fehler-Events.

- Health Endpoint (optional):
- `--health-server --health-host 127.0.0.1 --health-port 8765`
- Endpoint: `GET /health` oder `GET /healthz`
- Falls Socket-Binding fehlschlaegt, laeuft ACC weiter und schreibt ein Warn-/Log-Event.

## Tick-Modell

- Pro Tick wird `orchestrator.run(cycles=daemon_cycles_per_tick)` ausgeführt.
- Danach wartet der Prozess `daemon_interval` Sekunden.
- Zyklusnummern bleiben global fortlaufend.

## Begrenzter Testlauf

```bash
python3 main.py --daemon --daemon-max-ticks 3 --daemon-interval 0.2 --daemon-cycles-per-tick 2 \
  --daemon-lock-path data/acc.lock \
  --structured-logs --structured-log-path data/acc_service.log.jsonl
```

## Stop-Verhalten

- `Ctrl+C` beendet den Daemon sauber (`KeyboardInterrupt`).
- DB-Verbindung wird im `finally`-Block geschlossen.
