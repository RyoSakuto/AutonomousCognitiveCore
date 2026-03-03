# REPO.md (For Dummies) - ACC einfach erklaert

## 1. Was ist das hier?

Dieses Repo ist ein **autonomer Denk-Kern**.

Kurz gesagt:
- Das System startet eigene Denkzyklen.
- Es erzeugt eigene interne Ziele.
- Es bewertet seine Ideen selbst.
- Es merkt sich Vergangenes in einer Datenbank.
- Es kann kleine Laufzeit-Parameter vorsichtig selbst anpassen (mit Sicherheitsregeln).

Wichtig:
- Das ist **kein Bewusstsein**.
- Das ist ein **technischer Autonomie-Prototyp**.

## 2. Was brauche ich, damit es laeuft?

- Python 3.10+
- Schreibrechte im Ordner `data/`

Optional:
- Ollama lokal, wenn du lokale LLM/Embeddings nutzen willst.

## 3. Wie starte ich es (einfach)?

Ein normaler Lauf:

```bash
python3 main.py --cycles 12
```

Was passiert dann?
- Es rechnet 12 Zyklen.
- Am Ende zeigt es dir eine kurze Zusammenfassung.
- Alles wird in `data/acc.db` gespeichert.

## 4. Wie starte ich es als "Selbstlaeufer"?

Daemon-Modus (laeuft immer weiter):

```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5
```

Bedeutung:
- `--daemon-cycles-per-tick 4` -> pro Takt 4 Denkzyklen
- `--daemon-interval 5` -> danach 5 Sekunden warten

Stoppen:
- `Ctrl + C`

## 5. Wie teste ich den Daemon kurz?

```bash
python3 main.py --daemon --daemon-max-ticks 3 --daemon-interval 0.2 --daemon-cycles-per-tick 2
```

Das laeuft nur 3 Takte und beendet sich dann von selbst.

## 6. Wo sind die wichtigsten Dateien?

- `main.py` -> Startpunkt (normal + daemon)
- `acc/orchestrator.py` -> Hauptlogik des Denkzyklus
- `acc/self_modification.py` -> Sicherheitsregeln fuer Selbstanpassung
- `acc/memory.py` -> Semantischer Speicher (Wiederfinden alter Inhalte)
- `acc/embedding.py` -> Embeddings (`hash` oder `ollama`)
- `acc/state.py` -> DB-Zugriff und Zustand
- `acc/db.py` -> SQLite-Schema
- `docs/` -> Ausfuehrliche technische Doku

## 7. Was kann das System aktuell konkret?

- Interne Ziele generieren (ohne externen Prompt)
- Unsicherheit/Konflikte/Neuheit messen
- Hypothesen erzeugen und bewerten (`commit` / `explore`)
- Counterfactual-Branches erzeugen
- Relevante alte Inhalte aus Memory in neue Prompts holen
- Laufzeit-Parameter mit Sicherheits-Gates anpassen
- Bei schlechter Entwicklung Anpassungen zurueckrollen

## 8. Was bedeutet "Safety-Gated Self-Modification"?

Das System darf **nicht einfach irgendwas** aendern.

Es macht stattdessen:
1. Vorschlag erzeugen
2. Gate-Pruefung (erlaubt? im Bereich? Delta klein genug?)
3. Simulationsscore
4. Nur bei Erfolg anwenden
5. Spaeter pruefen und ggf. rollback

Alles wird protokolliert in der DB:
- `runtime_params`
- `self_mod_proposals`
- `self_mod_audit`

## 9. Wie schaue ich schnell, ob es lebt?

```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('data/acc.db')
conn.row_factory = sqlite3.Row
print('latest_run', dict(conn.execute("SELECT id,cycles,autonomous_tasks,round(avg_uncertainty,3) avg_u FROM runs ORDER BY id DESC LIMIT 1").fetchone()))
print('last_cycle', conn.execute("SELECT MAX(cycle) FROM metrics").fetchone()[0])
print('self_mod', [dict(r) for r in conn.execute("SELECT status,COUNT(*) c FROM self_mod_proposals GROUP BY status")])
PY
```

Wenn hier Daten kommen, arbeitet dein Core.

## 10. Optional: Lokale Modelle (Ollama)

Text-LLM:

```bash
python3 main.py --cycles 12 --llm-provider ollama --llm-model llama3.1
```

Embeddings:

```bash
python3 main.py --cycles 12 --embedding-provider ollama --embedding-model nomic-embed-text
```

Wenn Ollama ausfaellt, faellt ACC automatisch auf sichere Standard-Logik zurueck.

## 11. Typische Probleme (einfach)

Problem: "Es passiert zu wenig" (viele idle-Zyklen)
- Mehr Zyklen laufen lassen
- Daemon-Modus nutzen
- spaeter Trigger etwas aggressiver einstellen

Problem: "Zu viele Branches"
- Exploration-Faktor reduzieren

Problem: "Keine Self-Mod Proposals"
- Langer laufen lassen (z. B. 20+ Zyklen)
- Self-Mod nicht deaktivieren

## 12. Mini-Merksatz

Wenn du nur einen Befehl merken willst:

```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5
```

Das ist dein aktueller Selbstlaeufer-Start.

## 13. Neuer Kern fuer "echte Aufgaben"

Zusatz seit Runde 2:
- Es gibt jetzt einen einheitlichen Task-Core in der DB:
- `tasks` (Aufgaben)
- `task_dependencies` (Abhaengigkeiten zwischen Aufgaben)
- `task_runs` (Ausfuehrungen)
- `task_reviews` (Bewertungen)
- `agent_events` (Ereignisse)

Damit kann ACC schon:
- Aufgaben anlegen
- Aufgaben nach Prioritaet claimen
- Laufdaten/Logs speichern
- Reviews protokollieren
- Agent-Events sauber dokumentieren

Typische Status jetzt:
- `idea` (Roh-Idee)
- `creative` (Brainstorming)
- `queued` (wartet auf Ausfuehrung)
- `running` (wird bearbeitet)
- `rework` / `blocked` / `done` / `failed`

Neu:
- ACC kann jetzt automatisch pro Zyklus von `idea` nach `creative` und dann nach `queued` ueberfuehren.
- Wenn Human-Gate aktiv ist, landet ein reifer Task erst auf `blocked`, bis du ihn freigibst.
- `queued`-Tasks mit offenen Abhaengigkeiten werden automatisch ausgebremst.
- Fehler/Rework koennen automatisch mit Retry wieder in `queued` landen.
- Worker werden dynamisch nach Erfolg/Qualitaet/Last gewaehlt.

Schnellstart:
```bash
python3 main.py --create-task "Neue Feature-Idee ausarbeiten" --task-status idea
python3 main.py --task-funnel-now --task-human-gate
python3 main.py --list-tasks blocked
python3 main.py --approve-task TASK-00001 --feedback "Passt, umsetzen."
python3 main.py --execute-queue-now --task-exec-batch 2
```

Worker-Routing (neu):
```bash
python3 main.py --create-task "Memory-Analyse" --task-status queued --task-worker nimcf
python3 main.py --create-task "Delegations-Task" --task-status queued --task-worker kidiekiruft
python3 main.py --execute-queue-now --task-exec-batch 4
```

KIdieKIruft live (optional, sonst immer dry-run):
```bash
python3 main.py --execute-queue-now \
  --kidiekiruft-live-dispatch \
  --kidiekiruft-worker-cmd "./scripts/worker_codex.sh {prompt_file}" \
  --kidiekiruft-worker-bin gpt
```

Wenn ein KIdieKIruft-Task bei ACC auf `blocked` steht:
```bash
python3 main.py --sync-kidiekiruft-now
```
Dann zieht ACC externe Reviews zurueck in den ACC-Status und importiert Run-Details.
Bei `rework` kann ACC den Task auto-requeue-en und zusaetzlich einen Rework-Follow-up-Task anlegen.

Gehaerteter Daemon (empfohlen):
```bash
python3 main.py --daemon --daemon-cycles-per-tick 4 --daemon-interval 5 \
  --daemon-lock-path data/acc_daemon.lock \
  --structured-logs --structured-log-path data/acc_service.log.jsonl \
  --health-server --health-host 127.0.0.1 --health-port 8765
```

Extra Safety-Profil:
```bash
python3 main.py --cycles 8 \
  --operating-mode production \
  --worker-allowlist acc \
  --self-mod-max-approved 1 --self-mod-budget-window 24
```

Wichtig:
- Der Kern ist jetzt deutlich weiter als die reine Foundation.
- Naechster Ausbau: echte DAG-Planung ueber viele Tasks und staerkere Safety-Policies pro Modus.
