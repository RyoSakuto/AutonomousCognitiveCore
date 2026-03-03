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
