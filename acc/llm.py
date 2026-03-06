from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from urllib import error, request

from .config import ACCConfig


class LLMClient:
    def generate(
        self,
        prompt: str,
        *,
        role: str | None = None,
        model: str | None = None,
        task_context: dict | None = None,
    ) -> str:
        raise NotImplementedError

    def list_models(self) -> dict[str, object]:
        return {
            "provider": "none",
            "loaded_models": [],
            "available_models": [],
            "active_model": None,
            "supports_loading": False,
            "supports_discovery": False,
            "role_models": {},
        }

    def load_model(self, model: str) -> dict[str, object]:
        return {
            "ok": False,
            "model": model,
            "message": "Model loading is not supported for this provider.",
        }


class NullLLMClient(LLMClient):
    def generate(
        self,
        prompt: str,
        *,
        role: str | None = None,
        model: str | None = None,
        task_context: dict | None = None,
    ) -> str:
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

    def generate(
        self,
        prompt: str,
        *,
        role: str | None = None,
        model: str | None = None,
        task_context: dict | None = None,
    ) -> str:
        target_model = model or self.model
        payload = {
            "model": target_model,
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
    base = _resolve_openai_root_endpoint(endpoint)
    return f"{base}/v1/chat/completions"


def _resolve_openai_root_endpoint(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/completions",
        "/v1/responses",
        "/v1/embeddings",
        "/api/v1/chat",
    ):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    if value.endswith("/v1"):
        return value[: -len("/v1")]
    if value.endswith("/api/v1"):
        return value[: -len("/api/v1")]
    return value


def _resolve_models_endpoint(endpoint: str) -> str:
    base = _resolve_openai_root_endpoint(endpoint)
    return f"{base}/v1/models"


def _resolve_model_catalog_endpoint(endpoint: str) -> str:
    base = _resolve_openai_root_endpoint(endpoint)
    return f"{base}/api/v1/models"


def _resolve_model_load_endpoint(endpoint: str) -> str:
    base = _resolve_openai_root_endpoint(endpoint)
    return f"{base}/api/v1/models/load"


def _extract_model_ids(payload: object) -> list[str]:
    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            if key in payload:
                return _extract_model_ids(payload.get(key))
        extracted: list[str] = []
        for key in ("id", "model", "identifier", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                extracted.append(value.strip())
        return extracted
    if isinstance(payload, list):
        extracted = []
        for item in payload:
            extracted.extend(_extract_model_ids(item))
        deduped: list[str] = []
        for item in extracted:
            if item not in deduped:
                deduped.append(item)
        return deduped
    return []


def _is_likely_text_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return not any(token in lowered for token in ("embed", "embedding", "rerank", "vision"))


def _normalize_role(role: str | None) -> str:
    token = (role or "default").strip().lower()
    aliases = {
        "llm_planner": "planner",
        "planner": "planner",
        "planning": "planner",
        "llm_reviewer": "reviewer",
        "reviewer": "reviewer",
        "review": "reviewer",
        "chat": "chat",
        "response": "chat",
        "external_response": "chat",
        "reasoning": "reasoning",
        "default": "default",
    }
    return aliases.get(token, token or "default")


@dataclass
class OpenAICompatibleClient(LLMClient):
    endpoint: str
    model: str
    timeout_sec: float
    api_key: str = ""
    auto_discover: bool = True
    auto_load: bool = False
    prefer_loaded: bool = True
    load_timeout_sec: float = 120.0
    switch_budget: int = 1
    planner_model: str = ""
    reviewer_model: str = ""
    chat_model: str = ""
    active_model: str = ""
    switches_made: int = 0
    last_route_meta: dict[str, object] = field(default_factory=dict)

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        timeout_sec: float | None = None,
    ) -> tuple[object | None, str | None]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout_sec or self.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            return None, f"HTTP {exc.code}: {detail}"
        except (error.URLError, TimeoutError) as exc:
            return None, str(exc)

        try:
            return json.loads(body), None
        except json.JSONDecodeError:
            return None, "invalid_json"

    def _discover_models(self) -> dict[str, object]:
        loaded_models: list[str] = []
        available_models: list[str] = []

        loaded_payload, loaded_error = self._request_json(_resolve_models_endpoint(self.endpoint), method="GET")
        if loaded_payload is not None:
            loaded_models = [name for name in _extract_model_ids(loaded_payload) if _is_likely_text_model(name)]

        catalog_payload, catalog_error = self._request_json(
            _resolve_model_catalog_endpoint(self.endpoint),
            method="GET",
        )
        if catalog_payload is not None:
            available_models = [
                name for name in _extract_model_ids(catalog_payload) if _is_likely_text_model(name)
            ]

        if not available_models:
            available_models = list(loaded_models)

        active_model: str | None = None
        if self.active_model and self.active_model in loaded_models:
            active_model = self.active_model
        elif self.model in loaded_models:
            active_model = self.model
        elif loaded_models:
            active_model = loaded_models[0]

        return {
            "provider": "openai_compatible",
            "loaded_models": loaded_models,
            "available_models": available_models,
            "active_model": active_model,
            "supports_loading": True,
            "supports_discovery": loaded_payload is not None or catalog_payload is not None,
            "role_models": {
                "default": self.model,
                "planner": self.planner_model or None,
                "reviewer": self.reviewer_model or None,
                "chat": self.chat_model or None,
            },
            "errors": {
                "loaded": loaded_error,
                "available": catalog_error,
            },
            "switches_made": self.switches_made,
            "switch_budget": self.switch_budget,
        }

    def list_models(self) -> dict[str, object]:
        return self._discover_models()

    def _heuristic_role_model(self, role: str, candidates: list[str]) -> str | None:
        if not candidates:
            return None

        role_token = _normalize_role(role)

        def _score(name: str) -> tuple[int, int]:
            lowered = name.lower()
            score = 0
            if role_token == "planner":
                if any(token in lowered for token in ("reason", "reasoning", "think", "planner", "ministral")):
                    score += 7
                if any(token in lowered for token in ("gpt-oss", "instruct", "chat")):
                    score += 2
            elif role_token == "reviewer":
                if any(token in lowered for token in ("gpt-oss", "gpt", "instruct", "judge", "review")):
                    score += 7
                if "reason" in lowered:
                    score += 3
            elif role_token == "chat":
                if any(token in lowered for token in ("gpt-oss", "gpt", "chat", "instruct")):
                    score += 7
                if "reason" in lowered:
                    score += 1
            else:
                if self.model and lowered == self.model.lower():
                    score += 8
                if self.active_model and lowered == self.active_model.lower():
                    score += 4
            return score, -len(name)

        ranked = sorted(candidates, key=_score, reverse=True)
        return ranked[0] if ranked else None

    def _role_target_model(self, role: str, task_context: dict | None = None) -> str | None:
        context = task_context or {}
        for key in ("llm_model", "model"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        role_token = _normalize_role(role)
        if role_token == "planner" and self.planner_model:
            return self.planner_model
        if role_token == "reviewer" and self.reviewer_model:
            return self.reviewer_model
        if role_token == "chat" and self.chat_model:
            return self.chat_model
        return self.model or None

    def _can_switch_to(self, target_model: str | None) -> bool:
        if not target_model:
            return False
        if not self.active_model or self.active_model == target_model:
            return True
        if self.switch_budget < 0:
            return True
        return self.switches_made < self.switch_budget

    def _mark_active_model(self, model_name: str | None) -> None:
        if not model_name:
            return
        if self.active_model and self.active_model != model_name:
            self.switches_made += 1
        self.active_model = model_name

    def load_model(self, model: str) -> dict[str, object]:
        target = model.strip()
        if not target:
            return {"ok": False, "model": model, "message": "Missing model name."}

        discovered = self._discover_models()
        loaded_models = list(discovered.get("loaded_models", []))
        if target in loaded_models:
            self._mark_active_model(target)
            return {"ok": True, "model": target, "message": "Model already loaded.", "loaded": True}

        payload_variants = (
            {"model": target},
            {"identifier": target},
            {"id": target},
        )
        last_error = "unknown"
        for payload in payload_variants:
            _, load_error = self._request_json(
                _resolve_model_load_endpoint(self.endpoint),
                method="POST",
                payload=payload,
                timeout_sec=self.load_timeout_sec,
            )
            if load_error is None:
                last_error = ""
                break
            last_error = load_error

        deadline = time.time() + max(self.load_timeout_sec, 1.0)
        while time.time() < deadline:
            refreshed = self._discover_models()
            refreshed_loaded = list(refreshed.get("loaded_models", []))
            if target in refreshed_loaded:
                self._mark_active_model(target)
                return {"ok": True, "model": target, "message": "Model loaded.", "loaded": True}
            time.sleep(0.75)

        return {
            "ok": False,
            "model": target,
            "message": f"Model load not confirmed within timeout. last_error={last_error}",
            "loaded": False,
        }

    def _resolve_target_model(
        self,
        *,
        role: str | None,
        requested_model: str | None,
        task_context: dict | None,
    ) -> str:
        role_token = _normalize_role(role)
        target_model = requested_model.strip() if isinstance(requested_model, str) and requested_model.strip() else None
        if target_model is None:
            target_model = self._role_target_model(role_token, task_context)

        discovery = self._discover_models() if self.auto_discover else self.list_models()
        loaded_models = list(discovery.get("loaded_models", []))
        available_models = list(discovery.get("available_models", []))
        heuristic_loaded = self._heuristic_role_model(role_token, loaded_models)
        heuristic_available = self._heuristic_role_model(role_token, available_models)

        chosen_model = target_model or heuristic_loaded or heuristic_available or self.model
        route_reason = "configured"
        loaded = chosen_model in loaded_models

        if loaded:
            route_reason = "loaded_target"
        elif self.prefer_loaded and heuristic_loaded:
            if chosen_model != target_model or not self.auto_load:
                chosen_model = heuristic_loaded
                loaded = True
                route_reason = "prefer_loaded"

        if (
            not loaded
            and self.auto_load
            and chosen_model
            and chosen_model in available_models
            and self._can_switch_to(chosen_model)
        ):
            load_result = self.load_model(chosen_model)
            if bool(load_result.get("ok")):
                loaded = True
                route_reason = "auto_loaded"

        if not loaded and self.prefer_loaded and loaded_models:
            fallback_loaded = heuristic_loaded or loaded_models[0]
            if fallback_loaded:
                chosen_model = fallback_loaded
                loaded = True
                route_reason = "loaded_fallback"

        if loaded:
            self._mark_active_model(chosen_model)

        self.last_route_meta = {
            "role": role_token,
            "requested_model": requested_model,
            "configured_target": target_model,
            "chosen_model": chosen_model,
            "route_reason": route_reason,
            "loaded_models": loaded_models,
            "available_models": available_models,
            "active_model": self.active_model or None,
            "switches_made": self.switches_made,
            "switch_budget": self.switch_budget,
        }
        return chosen_model or self.model

    def generate(
        self,
        prompt: str,
        *,
        role: str | None = None,
        model: str | None = None,
        task_context: dict | None = None,
    ) -> str:
        url = _resolve_chat_completions_endpoint(self.endpoint)
        target_model = self._resolve_target_model(
            role=role,
            requested_model=model,
            task_context=task_context,
        )
        payload = {
            "model": target_model,
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
            auto_discover=config.llm_auto_discover,
            auto_load=config.llm_auto_load,
            prefer_loaded=config.llm_prefer_loaded,
            load_timeout_sec=config.llm_load_timeout_sec,
            switch_budget=config.llm_switch_budget,
            planner_model=config.llm_planner_model,
            reviewer_model=config.llm_reviewer_model,
            chat_model=config.llm_chat_model,
        )
    return NullLLMClient()
