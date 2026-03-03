from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional, Set

from core.domain import MemoryManagerProtocol
from memory.db import add_episode, get_episodes, init_db
from memory.retrieval import retrieve_relevant


class MemoryManager(MemoryManagerProtocol):
    """Combines short-term cache and persistent episodic memory."""

    def __init__(self, short_term_limit: int = 20) -> None:
        self.short_term_limit = short_term_limit
        self._short_term: Deque[Dict[str, float | str]] = deque(maxlen=short_term_limit)
        self._booted = False

    def initialize(self) -> None:
        if not self._booted:
            init_db()
            self._booted = True

    PRIORITY_KEYWORDS: Set[str] = frozenset(
        {
            "fehler",
            "problem",
            "notfall",
            "erfolg",
            "kritisch",
            "neu",
            "wichtig",
            "lernen",
        }
    )

    def add_experience(
        self,
        text: str,
        affect_hint: Optional[Dict[str, float]] = None,
        importance: Optional[float] = None,
        source: str = "module",
    ) -> Dict[str, object]:
        affect_hint = affect_hint or {}
        computed_importance = (
            self._estimate_importance(text, affect_hint) if importance is None else float(importance)
        )
        entry: Dict[str, object] = {
            "text": text,
            "valenz": float(affect_hint.get("valenz", 0.0)),
            "arousal": float(affect_hint.get("arousal", 0.0)),
            "importance": max(0.0, min(computed_importance, 10.0)),
            "source": source,
        }
        episode_id = add_episode(
            text,
            valenz=entry["valenz"],
            arousal=entry["arousal"],
            importance=entry["importance"],
            source=source,
        )
        entry["episode_id"] = episode_id
        self._short_term.appendleft(entry)
        return entry

    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, object]]:
        results = []
        for item in self._short_term:
            if query.lower() in item["text"].lower():
                results.append({"id": item.get("episode_id", -1), "text": item["text"], "score": 1.0})
        long_term = retrieve_relevant(query, k=k)
        combined = results + long_term
        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined[:k]

    def recent_experiences(self, limit: int = 50) -> List[Dict[str, object]]:
        rows = get_episodes(limit)
        result: List[Dict[str, object]] = []
        for ep in rows:
            result.append(
                {
                    "id": ep[0],
                    "ts": ep[1],
                    "text": ep[2],
                    "valenz": ep[3],
                    "arousal": ep[4],
                    "importance": ep[5],
                }
            )
        return result

    def _tokenize(self, text: str) -> Set[str]:
        return {tok.strip(".,!?").lower() for tok in text.split() if tok}

    def _novelty_score(self, text: str) -> float:
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0
        if not self._short_term:
            return 1.0
        max_overlap = 0.0
        for item in self._short_term:
            other_tokens = self._tokenize(str(item.get("text", "")))
            union = tokens.union(other_tokens)
            if not union:
                continue
            overlap = len(tokens.intersection(other_tokens)) / len(union)
            if overlap > max_overlap:
                max_overlap = overlap
        return max(0.0, 1.0 - max_overlap)

    def _keyword_bonus(self, text: str) -> float:
        tokens = self._tokenize(text)
        return 1.0 if any(token in self.PRIORITY_KEYWORDS for token in tokens) else 0.0

    def _estimate_importance(self, text: str, affect_hint: Dict[str, float]) -> float:
        arousal = float(affect_hint.get("arousal", 0.0))
        novelty = self._novelty_score(text)
        keyword = self._keyword_bonus(text)
        importance = 5.0 + 2.0 * novelty + 2.0 * arousal + 1.0 * keyword
        return max(0.0, min(importance, 10.0))
