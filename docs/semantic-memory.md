# Semantische Langzeit-Erinnerung

## Zweck

Semantische Erinnerung reduziert Wiederholungen und macht Hypothesen konsistenter, indem frühere Goal- und Hypotheseninhalte wiederverwendet werden.

## Komponenten

- `acc/embedding.py`
- `HashEmbedder`: deterministisch, lokal, ohne externe Abhängigkeit
- `OllamaEmbedder`: optionaler lokaler Embedding-Endpoint mit Hash-Fallback

- `acc/memory.py`
- Persistiert Embeddings in `memory_embeddings`
- Führt Similarity-Suche per Cosine Similarity aus

## Retrieval-Mechanik

1. Query-Text wird eingebettet.
2. Letzte `memory_candidate_window` Einträge werden geladen.
3. Cosine Similarity wird berechnet.
4. Treffer über `memory_min_score` werden sortiert.
5. Top-`memory_retrieval_k` Treffer gehen in den Prompt.

## Auditierbarkeit

- Jeder Retrieval-Vorgang wird als Episode `memory_retrieved` gespeichert.
- Quelle jedes Memory-Snippets ist nachvollziehbar (`source_kind:source_id`).

## Grenzen (aktueller Stand)

- Kein ANN-Index; lineare Suche über ein Fenster (bewusst simpel für MVP+).
- Keine semantische Deduplizierung ähnlicher Texte.
- Keine TTL/Decay-Policy für alte Erinnerungen.
