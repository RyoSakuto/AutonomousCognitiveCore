from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request

from .config import ACCConfig


class LLMClient:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class NullLLMClient(LLMClient):
    def generate(self, prompt: str) -> str:
        prompt_head = prompt.strip().splitlines()[0][:100] if prompt.strip() else "internal"
        return (
            "Heuristic proposal: decompose the target goal into two checks, "
            "prioritize uncertainty reduction, then run a coherence re-check. "
            f"Context focus: {prompt_head}"
        )


@dataclass
class OllamaClient(LLMClient):
    endpoint: str
    model: str
    timeout_sec: float

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        req = request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except (error.URLError, TimeoutError) as exc:
            return f"Ollama unavailable ({exc}). Fallback: execute deterministic uncertainty-reduction plan."

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return "Ollama response parse failed. Fallback: execute deterministic conflict-resolution plan."

        text = data.get("response", "").strip()
        if not text:
            return "Ollama returned empty output. Fallback: perform conservative coherence audit."
        return text


def _resolve_chat_completions_endpoint(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    if value.endswith("/v1/chat/completions") or value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return f"{value}/chat/completions"
    return f"{value}/v1/chat/completions"


@dataclass
class OpenAICompatibleClient(LLMClient):
    endpoint: str
    model: str
    timeout_sec: float
    api_key: str = ""

    def generate(self, prompt: str) -> str:
        url = _resolve_chat_completions_endpoint(self.endpoint)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an autonomous reasoning module. "
                        "Respond clearly, concisely, and helpfully in plain text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except (error.URLError, TimeoutError) as exc:
            return (
                f"OpenAI-compatible endpoint unavailable ({exc}). "
                "Fallback: execute deterministic uncertainty-reduction plan."
            )

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return "OpenAI-compatible response parse failed. Fallback: perform conservative coherence audit."

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return "OpenAI-compatible response missing choices. Fallback: use deterministic conflict-resolution plan."

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            text = " ".join(parts).strip()
        else:
            text = ""

        if not text:
            return "OpenAI-compatible model returned empty output. Fallback: run conservative coherence audit."
        return text


def build_llm_client(config: ACCConfig) -> LLMClient:
    provider = config.llm_provider.lower()
    if provider == "ollama":
        return OllamaClient(
            endpoint=config.llm_endpoint,
            model=config.llm_model,
            timeout_sec=config.llm_timeout_sec,
        )
    if provider in {"openai_compatible", "openai", "lmstudio"}:
        return OpenAICompatibleClient(
            endpoint=config.llm_endpoint,
            model=config.llm_model,
            timeout_sec=config.llm_timeout_sec,
            api_key=config.llm_api_key,
        )
    return NullLLMClient()
