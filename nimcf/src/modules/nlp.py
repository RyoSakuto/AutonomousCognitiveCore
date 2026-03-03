from __future__ import annotations

from typing import Dict, List

from core.domain import TaskSpec
from modules.base import ModuleResult, NeuroModule


class SemanticRetrievalModule(NeuroModule):
    name = "semantic_retriever"
    capabilities = frozenset({"memory-search", "language"})
    priority = 0.9

    def run(self, task: TaskSpec, context) -> ModuleResult:
        query = task.payload.get("query") or task.goal
        k = int(task.metadata.get("top_k", 5))
        hits = context.memory.retrieve(query, k=k)
        traces: Dict[str, List[Dict[str, object]]] = {"hits": hits}
        return ModuleResult(output=hits, confidence=0.6 if hits else 0.2, traces=traces)
