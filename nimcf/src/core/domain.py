from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set


@dataclass
class TaskSpec:
    """Describes an intention the coordinator should route to modules."""

    goal: str
    payload: Dict[str, Any] = field(default_factory=dict)
    capabilities: Set[str] = field(default_factory=set)
    urgency: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleActivation:
    """Captures an execution of a module for graph analytics."""

    module_name: str
    task_goal: str
    confidence: float
    outcome: Any
    tags: Set[str] = field(default_factory=set)


@dataclass
class CoordinatorContext:
    """Runtime context handed to modules for memory and collaboration."""

    memory: "MemoryManagerProtocol"
    cognitive_map: "CognitiveMapProtocol"
    history: Sequence[ModuleActivation] = field(default_factory=list)


class MemoryManagerProtocol:
    def add_experience(
        self,
        text: str,
        affect_hint: Optional[Dict[str, float]] = None,
        importance: Optional[float] = None,
        source: str = "module",
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def recent_experiences(self, limit: int = 50) -> List[Dict[str, Any]]:
        raise NotImplementedError


class CognitiveMapProtocol:
    def record_activation(self, activation: ModuleActivation) -> None:
        raise NotImplementedError

    def co_activations(
        self, module_name: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError
