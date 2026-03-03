from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Set

from core.domain import CoordinatorContext, TaskSpec


@dataclass
class ModuleResult:
    output: Any
    confidence: float = 0.0
    traces: Dict[str, Any] = field(default_factory=dict)
    follow_up: Dict[str, Any] = field(default_factory=dict)


class NeuroModule:
    """Base implementation for neuro-modules."""

    name: str = "base"
    capabilities: Set[str] = frozenset()
    priority: float = 1.0

    def prepare(self, context: CoordinatorContext) -> None:
        """Hook for warm-up logic."""

    def is_applicable(self, task: TaskSpec) -> bool:
        """Decide whether module should run for a task."""
        if not self.capabilities:
            return True
        return bool(self.capabilities.intersection(task.capabilities))

    def run(self, task: TaskSpec, context: CoordinatorContext) -> ModuleResult:
        raise NotImplementedError

    def receive_feedback(self, reward: float, metadata: Dict[str, Any] | None = None) -> None:
        """Adjust internal state after reinforcement."""

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "priority": self.priority,
            "class": self.__class__.__name__,
        }
