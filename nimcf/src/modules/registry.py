from __future__ import annotations

from typing import Dict, List, Sequence

from core.domain import CoordinatorContext, TaskSpec
from .base import NeuroModule


class ModuleRegistry:
    """Holds the dynamic list of neuro-modules."""

    def __init__(self) -> None:
        self._modules: Dict[str, NeuroModule] = {}

    @property
    def modules(self) -> Sequence[NeuroModule]:
        return tuple(self._modules.values())

    def register(self, module: NeuroModule) -> None:
        if module.name in self._modules:
            raise ValueError(f"Module name '{module.name}' already registered.")
        self._modules[module.name] = module

    def get(self, name: str) -> NeuroModule:
        return self._modules[name]

    def prepare_all(self, context: CoordinatorContext) -> None:
        for module in self._modules.values():
            module.prepare(context)

    def ranked_for_task(self, task: TaskSpec) -> List[NeuroModule]:
        filtered = [m for m in self._modules.values() if m.is_applicable(task)]
        return sorted(filtered, key=lambda m: m.priority, reverse=True)
