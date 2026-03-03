from __future__ import annotations

from collections import defaultdict
import unicodedata
from typing import Dict, List

from core.domain import CoordinatorContext, TaskSpec
from modules.base import ModuleResult, NeuroModule


class TopicClusteringModule(NeuroModule):
    name = "topic_clusterer"
    capabilities = frozenset({"topic-cluster", "categorize"})
    priority = 0.75

    TOPIC_KEYWORDS: Dict[str, List[str]] = {
        "energie": ["solar", "energie", "strom", "speicher", "netz", "panel"],
        "diagnose": ["fehler", "diagnose", "debug", "problem", "code", "404"],
        "garten": ["garten", "pflanz", "pflanze", "tomate", "erde", "gartner"],
        "lernprotokoll": ["lernen", "studie", "notiz", "test", "erkenntnis"],
        "emotion": ["glücklich", "traurig", "ärger", "freude", "stress"],
    }

    def run(self, task: TaskSpec, context: CoordinatorContext) -> ModuleResult:
        limit = int(task.metadata.get("limit", 50))
        episodes = context.memory.recent_experiences(limit)
        clusters: Dict[str, List[Dict[str, object]]] = defaultdict(list)

        for episode in episodes:
            topics = self._infer_topics(str(episode.get("text", "")))
            if not topics:
                topics = ["allgemein"]
            for topic in topics:
                clusters[topic].append(
                    {
                        "id": episode.get("id"),
                        "importance": episode.get("importance", 0.0),
                        "text": episode.get("text", ""),
                    }
                )

        summary = []
        for topic, entries in clusters.items():
            entries.sort(key=lambda item: float(item.get("importance", 0.0)), reverse=True)
            summary.append(
                {
                    "topic": topic,
                    "count": len(entries),
                    "top_examples": entries[: min(3, len(entries))],
                }
            )

        summary.sort(key=lambda item: item["count"], reverse=True)
        confidence = 0.6 if summary else 0.2
        traces = {"clusters": summary[:5]}
        return ModuleResult(output=summary, confidence=confidence, traces=traces)

    def _infer_topics(self, text: str) -> List[str]:
        tokens = [self._normalize(tok) for tok in text.split()] if text else []
        scores: Dict[str, int] = {}
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            score = sum(1 for token in tokens for kw in keywords if token.startswith(kw))
            if score > 0:
                scores[topic] = score
        if not scores:
            return []
        max_score = max(scores.values())
        threshold = max(1, max_score - 1)
        return [topic for topic, score in scores.items() if score >= threshold]

    @staticmethod
    def _normalize(token: str) -> str:
        lowered = token.lower().strip(".,!?")
        return "".join(
            char for char in unicodedata.normalize("NFD", lowered) if unicodedata.category(char) != "Mn"
        )
