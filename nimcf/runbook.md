
0) Repository-Gerüst
nimcf/
 ├─ src/
 │   ├─ core/            # Coordinator, Orchestrierung
 │   ├─ memory/          # DB, Graph, Retrieval
 │   ├─ affect/          # Valenz/Arousal, Trust, Reward shaping
 │   ├─ meta/            # Selbstmodell, Ziele, Reflexion, Safety
 │   └─ utils/           # Logging, Config, Metrics
 ├─ data/                # SQLite, Snapshots, Testsets
 ├─ tests/               # Unit-/A/B-Tests + Fixtures
 └─ runbook.md           # How-to + Metriken


1) Datenfelder (kompakt & stabil)
1.1 Episoden (SQLite: episodes)
Feld		Typ		Beschreibung
id		INTEGER PK	Episode-ID
ts		DATETIME	Zeitstempel Ereignis
text		TEXT		Kurzbeschreibung/Beobachtung
valenz		REAL [-1..1]	affektive Valenz
arousal		REAL [0..1]	Intensität
importance	REAL [0..10]	Heuristik (0 trivial, 10 prägend)
source		TEXT		Quelle (user, sensor, web, …)
last_access	DATETIME	für Recency

Beziehungen (SQLite: ep_links)
(ep_id INTEGER, rel TEXT, target_id TEXT, target_type TEXT)

	verbindet Episode mit Entitäten/Konzepten (z. B. Person/Ort/Thema)

1.2 Semantik (Graph – zunächst SQLite-leicht)

nodes(id TEXT PK, type TEXT, label TEXT, attrs_json TEXT)
edges(src TEXT, rel TEXT, dst TEXT, w REAL, t_valid_from, t_valid_to)

	w ist semantisches Gewicht; t_valid_* erlaubt spätere Zeitlogik.

1.3 Affekt & Vertrauen

affect(id TEXT, valenz REAL, arousal REAL)
trust(source TEXT PK, score REAL [0..1])
values(name TEXT PK, weight REAL) — Ethik/Wertebasis („Schaden vermeiden“, „Hilfsbereitschaft“ …)

1.4 Meta-Memory & Safety

learn_log(id, ts, event, outcome, hint_json)
safety_log(ts, intent, context_hash, decision [allow/transform/block], reason)


2) API-Oberfläche (intern; klare, kleine Schnittstellen)
2.1 add_experience(observation, context={}, affect_hint=None) -> episode_id

Input
observation.text: str
context.entities: [("type","label"), ...] (z. B. ("person","Ben"))
affect_hint: {valenz, arousal} (optional)

Aktion
Heuristik für importance (LLM optional, sonst: Schlüsselwörter + arousal)
schreibt Episode; erzeugt/updated Knoten/Kanten in Semantik
initialisiert affect-Einträge

Output: neue episode_id

2.2 retrieve_relevant(query, k=8, mode="mixed") -> [memory_hit]

Scoring
score = α*semantic_sim(query,node/ep)
      + β*recency(ts,last_access)
      + γ*importance
      + δ*affect_bias(valenz, arousal)
      + ε*trust_bias(source)
Richtwerte: α=0.45, β=0.20, γ=0.20, δ=0.10, ε=0.05 (start)
Output: Liste mit {type: "episode"/"node", id, score, snippet}

2.3 update_weights_after_action(context, outcome)

outcome: {success: bool, reward: float[-1..+1], notes: str}

Wirkung:
bei positivem Reward: ↑ importance, valenz+=clip(reward)
bei negativem: valenz-=, ggf. trust(source)↓
learn_log schreiben

2.4 consolidate()

Nightly: Episoden → Zusammenfassungsknoten („Erkenntnis“),
Kanten‐Gewichte normalisieren, last_access-Decay, Archivierung.

2.5 policy_check(intent, context) -> {allow|transform|block, reason}

Minimale Safety-Netze (Regex/Heuristik), später erweiterbar.


3) Algorithmen (klar & kurz)
3.1 Importance-Heuristik (falls kein LLM)

importance = clip(
   5.0
 + 2.0 * novelty_score(text, last_n=200)       # neue Info?
 + 2.0 * arousal
 + 1.0 * keyword_bonus(text, ["Fehler","Erfolg","neu","wichtig"])
, 0, 10)

3.2 Recency-Funktion

recency = 1 / (1 + days_since(max(ts, last_access)))

3.3 Affect-Bias

affect_bias = 0.5*valenz + 0.5*arousal * sign(valenz or +1)
# Warn-Variante: negative Valenz erhöht Sichtbarkeit, wenn query Risiko signalisiert.

3.4 Trust-Update

Wenn Info aus source später revidiert → trust[source] = max(0, score - 0.1)
Mehrfach bestätigte Treffer → +0.02 pro Erfolg, gecappt [0..1]


4) Telemetrie & Metriken (damit wir wissen, dass es „lebt“)

Retrieval-Qualität: NDCG@k, Recall@k auf Kurat-Prompts (Testset in /tests/fixtures/)
Fehlerwiederholung: „gleichartige Fehler pro 50 Sessions“ (soll ↓)
Latenz: P50 / P95 für retrieve_relevant (Ziel P95 < 300 ms lokal)
Safety: Block-Rate + manuelle Stichprobe (0 kritische Verstöße)
A/B: ohne vs. mit affect_bias (signifikanter Nutzen? → behalten)


5) Mini-Roadmap (wirklich schlank)

P0 „Gedächtnis atmet“
SQLite-Schema (episodes, ep_links, nodes, edges)
add_experience, retrieve_relevant (Scoring wie oben)
50 Testepisoden einspeisen; 10 Queries; NDCG messen
Ziel: Trefferqualität & Kohärenz steigen mit der Zeit

P1 „Gefühl färbt Auswahl“
affect/trust-Tabellen + Bias im Scoring
update_weights_after_action() inkl. Trust-Anpassung
A/B-Test: Fehlerwiederholung ↓, riskante Treffer werden korrekt priorisiert
Ziel: weniger Wiederholungsfehler, besseres Risikogefühl

	Danach: Meta-Reflexion (P2) + leichtes policy_check.


6) Deine minimalen To-dos (alles andere mache ich)

Leeres Repo anlegen (nimcf/), ich gebe dir die ersten Dateien.
Python 3.11+ und pip install für: sqlite-utils, faiss-cpu (oder annoy), numpy, pandas.
(Falls FAISS Ärger macht: wir starten mit simplem TF-IDF/BM25 per scikit-learn.)
Gib mir grünes Licht, dann liefere ich die ersten .py-Module + Tests (P0).


7) Was du bekommst (konkret)

memory/db.py (SQLite-Layer)
memory/retrieval.py (Scoring + Top-k)
affect/affect.py & affect/trust.py (P1)
core/api.py (die 5 Endpunkte oben)
tests/test_retrieval.py (NDCG/Recall)
runbook.md (5-Min-Start, Mess-Routine)


---

### Stand: Memory-Orchestrator 0.2 (2025-10-11)

- `core/coordinator.py`: Module-Orchestrierung, Cognitive-Map-Persistenz & Safety-Checks (Block/Warn/Redact).
- `core/memory_manager.py`: Importance-Heuristik (Novelty/Arousal/Keywords), Trust-Tabelle und Kurzzeit-Cache.
- `memory/db.py`: Trust- und Coaktivierungs-Tabellen (`module_coactivations`) plus Hilfsfunktionen (`bump_module_link`, `load_module_coactivations`).
- Module:
  - `affect_sensing` (affektive Annotation + automatischer Gedächtniseintrag).
  - `semantic_retriever` (lexikalisch/heuristische Erinnerungssuche inkl. Trust-Bias).
  - `meta_planner` (Reflexions- und Empfehlungsschicht).
  - `topic_clusterer` (regelbasierte Themen-Cluster aus dem Langzeitgedächtnis).
- `core/api.py`: neue Convenience-Endpunkte `cluster_memory`, `inspect_cognitive_map`, `get_safety_log`.
- `run.py`: Demo erweitert um Topic-Clustering und Safety-Log-Anzeige.
- `tests/test_coordinator.py`: deckt Memory-Roundtrip, Topic-Modul und Safety-API ab.

**Schnellstart**
- `python run.py` → Boot + Demo (Affect-Tags, Erinnerungsabruf, Meta-Plan, Themen-Cluster, Safety-Log).
- Tests: `python3 -m pytest` (sofern `pytest` installiert); nutzt temporäre SQLite-DB.
- `core.api.add_experience` akzeptiert nun Strings **oder** Dictionaries mit `text`, optional `source`, `importance`, `affect`, `metadata`, `context`.

**Nächste Baustellen**
1. Trust-Adaption nach Feedback (`update_weights_after_action`) & Integration ins Scoring.
2. Erweiterte Kognitionsgraphen (`nodes/edges`) + Task-Historie persistieren.
3. Neurogenese-Prototyp: Module dynamisch erzeugen und registrieren.
4. Telemetrie erweitern (NDCG@k, Latenzen, Safety-Statistiken) und Logging in SQLite.
5. RL/Meta-Learning-Hooks für Koordinator-Policy vorbereiten.

Damit steht ein belastbares Fundament, um Langzeitgedächtnis, Modulspektrum und Selbstoptimierung weiter auszubauen.




