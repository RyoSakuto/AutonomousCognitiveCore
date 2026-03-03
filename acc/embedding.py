from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from math import sqrt
from urllib import error, request

from .config import ACCConfig


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize(vec: list[float]) -> list[float]:
    norm = sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


class Embedder:
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


@dataclass
class HashEmbedder(Embedder):
    dimensions: int = 96

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vec

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vec[idx] += sign * weight

        return _normalize(vec)


@dataclass
class OllamaEmbedder(Embedder):
    endpoint: str
    model: str
    timeout_sec: float
    fallback: HashEmbedder

    def embed(self, text: str) -> list[float]:
        payload = {
            "model": self.model,
            "prompt": text,
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
        except error.URLError:
            return self.fallback.embed(text)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self.fallback.embed(text)

        # Support both /api/embeddings and /api/embed style responses.
        raw = data.get("embedding")
        if raw is None and isinstance(data.get("embeddings"), list) and data["embeddings"]:
            raw = data["embeddings"][0]

        if not isinstance(raw, list) or not raw:
            return self.fallback.embed(text)

        vec: list[float] = []
        for value in raw:
            try:
                vec.append(float(value))
            except (TypeError, ValueError):
                return self.fallback.embed(text)

        return _normalize(vec)


def build_embedder(config: ACCConfig) -> Embedder:
    hash_embedder = HashEmbedder(dimensions=config.embedding_dimensions)
    if config.embedding_provider.lower() == "ollama":
        return OllamaEmbedder(
            endpoint=config.embedding_endpoint,
            model=config.embedding_model,
            timeout_sec=config.llm_timeout_sec,
            fallback=hash_embedder,
        )
    return hash_embedder
