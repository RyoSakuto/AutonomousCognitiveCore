from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict, List

from memory.db import bump_module_link, load_module_coactivations

from core.domain import ModuleActivation


class CognitiveMap:
    """Tracks co-activations between modules and surfaced task tags."""

    def __init__(self, window: int = 10) -> None:
        self._graph: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._recent: Deque[ModuleActivation] = deque(maxlen=window)
        self._storage_loaded = False

    def bootstrap_storage(self) -> None:
        if self._storage_loaded:
            return
        persisted = load_module_coactivations()
        for src, targets in persisted.items():
            for dst, weight in targets.items():
                self._graph[src][dst] = weight
        self._storage_loaded = True

    def record_activation(self, activation: ModuleActivation) -> None:
        if not self._storage_loaded:
            self.bootstrap_storage()
        for past in self._recent:
            if past.module_name == activation.module_name:
                continue
            self._graph[past.module_name][activation.module_name] += 1.0
            self._graph[activation.module_name][past.module_name] += 1.0
            bump_module_link(past.module_name, activation.module_name, 1.0)
            bump_module_link(activation.module_name, past.module_name, 1.0)
        self._recent.appendleft(activation)

    def co_activations(self, module_name: str, limit: int | None = None) -> List[Dict[str, float]]:
        if not self._storage_loaded:
            self.bootstrap_storage()
        neighbors = self._graph.get(module_name, {})
        ranked = sorted(neighbors.items(), key=lambda kv: kv[1], reverse=True)
        if limit is not None:
            ranked = ranked[:limit]
        return [{"module": name, "weight": weight} for name, weight in ranked]

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        if not self._storage_loaded:
            self.bootstrap_storage()
        return {module: dict(targets) for module, targets in self._graph.items()}
