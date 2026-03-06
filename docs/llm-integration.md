# Lokale LLM- und Embedding-Integration

## Text-Hypothesen (`acc/llm.py`)

### Modus `none` (Default)
- Nutzt `NullLLMClient`.
- Erzeugt deterministische heuristische Hypothesen.
- Vorteil: Keine externe Abhängigkeit, stabile Reproduzierbarkeit.

### Modus `ollama`
- Nutzt `OllamaClient` mit HTTP-POST an `/api/generate`.
- Bei Fehlern: sichere Fallback-Antwort statt Run-Abbruch.

### Modus `openai_compatible` (Alias: `openai`, `lmstudio`)
- Nutzt OpenAI-kompatibles Chat-Completions-Format.
- Endpoint kann als Base-URL angegeben werden (z. B. `http://192.168.0.56:1234`).
- Optionaler API-Key via `--llm-api-key` oder `ACC_LLM_API_KEY`.
- Bei Fehlern: sichere Fallback-Antwort statt Run-Abbruch.
- Geeignet fuer LM Studio (`/v1/chat/completions`).
- Empfohlen fuer langsamere lokale Reasoning-Modelle: `--llm-timeout 120` bis `180`.
- Wird auch von `--plan-goal`, `llm_planner` und `llm_reviewer` verwendet.

#### Auto-Discovery, RAM-schonendes Routing und Model-Load

- `ACC_LLM_AUTO_DISCOVER` / `--llm-auto-discover`
  - Fragt geladene Modelle ueber `/v1/models` ab.
- `ACC_LLM_AUTO_LOAD` / `--llm-auto-load`
  - Darf ein fehlendes Modell ueber `/api/v1/models/load` nachladen.
- `ACC_LLM_PREFER_LOADED` / `--llm-no-prefer-loaded`
  - Standard ist RAM-schonend: bereits geladene Modelle werden bevorzugt.
- `ACC_LLM_LOAD_TIMEOUT` / `--llm-load-timeout`
  - Zeitfenster fuer die Load-Bestaetigung.
- `ACC_LLM_SWITCH_BUDGET` / `--llm-switch-budget`
  - Begrenzt Modellwechsel pro ACC-Prozess, damit bei CPU/RAM-Betrieb nicht staendig umgeladen wird.
- Rollenmodelle:
  - `ACC_LLM_PLANNER_MODEL` / `--llm-planner-model`
  - `ACC_LLM_REVIEWER_MODEL` / `--llm-reviewer-model`
  - `ACC_LLM_CHAT_MODEL` / `--llm-chat-model`

Empfehlung fuer CPU-/RAM-Betrieb ohne viel VRAM:

- `--llm-auto-discover` aktiv lassen
- `--llm-no-prefer-loaded` **nicht** setzen
- `--llm-auto-load` nur aktivieren, wenn ACC Modelle wirklich selbst nachladen soll
- `--llm-switch-budget 1` oder `2` nutzen

Nutzbefehle:

```bash
python3 main.py \
  --llm-provider openai_compatible \
  --llm-endpoint http://192.168.0.56:1234 \
  --list-llm-models
```

```bash
python3 main.py \
  --llm-provider openai_compatible \
  --llm-endpoint http://192.168.0.56:1234 \
  --load-llm-model openai/gpt-oss-20b
```

## Embeddings (`acc/embedding.py`)

### Modus `hash` (Default)
- Deterministische Hash-Embeddings lokal im Prozess.
- Kein Netzwerk, kein Modell-Download.

### Modus `ollama`
- Nutzt lokalen Endpoint (`/api/embeddings` oder kompatible Antwortstruktur).
- Bei Fehlern: automatischer Fallback auf `HashEmbedder`.

## Startbeispiele

```bash
python3 main.py --cycles 12 --llm-provider ollama --llm-model llama3.1
```

```bash
python3 main.py --cycles 12 \
  --llm-provider openai_compatible \
  --llm-endpoint http://192.168.0.56:1234 \
  --llm-planner-model mistralai/ministral-3-14b-reasoning \
  --llm-reviewer-model openai/gpt-oss-20b \
  --llm-chat-model openai/gpt-oss-20b \
  --llm-switch-budget 1 \
  --llm-model mistralai/ministral-3-14b-reasoning
```

```bash
python3 main.py --cycles 12 --embedding-provider ollama --embedding-model nomic-embed-text
```

```bash
python3 main.py \
  --llm-provider ollama --llm-endpoint http://localhost:11434/api/generate \
  --embedding-provider ollama --embedding-endpoint http://localhost:11434/api/embeddings
```
