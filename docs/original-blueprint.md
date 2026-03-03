# Original Blueprint (Legacy)

Quelle: urspruengliches Konzeptdokument vor der technischen Umsetzung.

## Ziel

Ein System konstruieren, das:

- eigenstaendig Denkprozesse initiiert
- interne Zielhierarchien verwaltet
- Unsicherheit erkennt und reduziert
- Exploration betreibt
- persistente Zustaende ueber Zeit fuehrt
- eigene Hypothesen generiert und testet

Nicht: Bewusstsein.  
Nicht: Mystik.  
Sondern funktionale Autonomie.

## 1. Kernprinzip

Denken = iterative Selbstmodellierung unter interner Zielspannung.

Das System braucht nicht nur Input -> Output, sondern:

- interne Zustaende
- interne Spannungen
- interne Zielkonflikte
- Persistenz

## 2. Architekturelemente

### A. Persistent Internal State

- Langzeitspeicher (episodisch + semantisch)
- Selbstmodell (Faehigkeiten/Grenzen)
- Zielhistorie
- Erfolgsmuster

Technisch:

- Graphdatenbank oder SQLite + Embeddings
- Zeitstempel + Relevanzgewichtung

### B. Intrinsic Goal Generator

Externe Prompts duerfen nicht die einzige Zielquelle sein.

Metriken:

- Neugier (Informationsgewinn)
- Unsicherheit (Modellunsicherheit reduzieren)
- Kohaerenz (Widersprueche minimieren)
- Langfristige Stabilitaet

Task-Trigger:

- `internal_uncertainty > threshold`
- oder Goal-Konflikt
- oder hoher Neuheitswert

### C. Meta-Kognition

Das System muss:

- eigene Outputs bewerten
- Annahmen markieren
- alternative Hypothesen generieren
- Confidence-Scores berechnen

Ablauf:

1. Hypothese erzeugen
2. intern evaluieren
3. Schwachstellen identifizieren
4. erneut simulieren
5. committen oder explorieren

### D. Explorationsmechanismus

Nicht immer nur den wahrscheinlichsten Weg waehlen.

- Controlled deviation factor
- Hypothesis branching
- Simulierte Counterfactuals

Nicht Zufall, sondern Strategie.

### E. Self-Modification Layer

Fortgeschritten, optional:

- Toolchain erweitern
- Promptstrukturen anpassen
- interne Bewertungsgewichte veraendern

Regel:

- jede Aenderung muss durch Meta-Evaluation.

## 3. Minimaler Denkzyklus

```text
LOOP:
  observe internal state
  detect tension or uncertainty
  generate internal task
  simulate solution
  evaluate solution
  update self-model
END LOOP
```

Ohne externen Prompt.

## 4. Was dadurch entsteht

Ein System, das:

- nicht nur reagiert
- interne Spannungen abbaut
- eigene Fragen generiert
- eigene Struktur erweitert
