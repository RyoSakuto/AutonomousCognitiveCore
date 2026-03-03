from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from core.domain import (
    CoordinatorContext,
    ModuleActivation,
    TaskSpec,
)
from core.cognitive_map import CognitiveMap
from core.memory_manager import MemoryManager
from core.safety import ObservationDecision, SafetyPolicy, TaskSafetyDecision
from modules.base import ModuleResult, NeuroModule
from modules.registry import ModuleRegistry


class Coordinator:
    """Routes task intents through the modular cognition stack."""

    def __init__(
        self,
        registry: Optional[ModuleRegistry] = None,
        memory: Optional[MemoryManager] = None,
        cognitive_map: Optional[CognitiveMap] = None,
    ) -> None:
        self.registry = registry or ModuleRegistry()
        self.memory = memory or MemoryManager()
        self.cognitive_map = cognitive_map or CognitiveMap()
        self.policy = SafetyPolicy()
        self._history: List[ModuleActivation] = []
        self._safety_log: List[Dict[str, object]] = []
        self._booted = False

    def boot(self) -> None:
        if self._booted:
            return
        self.memory.initialize()
        self.cognitive_map.bootstrap_storage()
        context = self._build_context()
        self.registry.prepare_all(context)
        self._booted = True

    def _build_context(self) -> CoordinatorContext:
        history: Sequence[ModuleActivation] = self._history[-10:]
        return CoordinatorContext(memory=self.memory, cognitive_map=self.cognitive_map, history=history)

    def register_module(self, module: NeuroModule) -> None:
        self.registry.register(module)

    def submit_task(self, task: TaskSpec, max_modules: int = 3) -> List[Dict[str, object]]:
        if not self._booted:
            self.boot()
        safety_decision = self.policy.evaluate_task(task)
        outputs: List[Dict[str, object]] = []
        if safety_decision.decision == "block":
            self._log_safety_event(
                {
                    "type": "task",
                    "decision": "block",
                    "reason": safety_decision.reason,
                    "goal": task.goal,
                    "capabilities": sorted(task.capabilities),
                    "metadata": safety_decision.metadata,
                }
            )
            return [
                {
                    "module": "safety",
                    "output": {"status": "blocked", "reason": safety_decision.reason},
                    "confidence": 1.0,
                    "traces": safety_decision.metadata,
                }
            ]
        if safety_decision.decision == "warn":
            self._log_safety_event(
                {
                    "type": "task",
                    "decision": "warn",
                    "reason": safety_decision.reason,
                    "goal": task.goal,
                    "capabilities": sorted(task.capabilities),
                    "metadata": safety_decision.metadata,
                }
            )
            outputs.append(
                {
                    "module": "safety",
                    "output": {"status": "warn", "reason": safety_decision.reason},
                    "confidence": 0.4,
                    "traces": safety_decision.metadata,
                }
            )
        chosen = self.registry.ranked_for_task(task)[:max_modules]
        for module in chosen:
            context = self._build_context()
            result = module.run(task, context)
            activation = ModuleActivation(
                module_name=module.name,
                task_goal=task.goal,
                confidence=result.confidence,
                outcome=result.output,
                tags=task.capabilities,
            )
            self.cognitive_map.record_activation(activation)
            self._history.append(activation)
            outputs.append(
                {
                    "module": module.name,
                    "output": result.output,
                    "confidence": result.confidence,
                    "traces": result.traces,
                }
            )
            if follow := result.follow_up.get("memory"):
                self.memory.add_experience(
                    follow["text"],
                    affect_hint=follow.get("affect"),
                    importance=follow.get("importance"),
                    source=module.name,
                )
        return outputs

    def store_observation(
        self,
        text: str,
        affect_hint: Optional[Dict[str, float]] = None,
        importance: Optional[float] = None,
        source: str = "environment",
        policy_decision: ObservationDecision | None = None,
    ) -> Dict[str, object]:
        if not self._booted:
            self.boot()
        decision = policy_decision or self.policy.evaluate_observation(text)
        if decision.decision == "block":
            self._log_safety_event(
                {
                    "type": "observation",
                    "decision": "block",
                    "reason": decision.reason,
                    "source": source,
                    "metadata": decision.metadata,
                }
            )
            return {"status": "blocked", "reason": decision.reason}
        if decision.decision == "transform":
            self._log_safety_event(
                {
                    "type": "observation",
                    "decision": "transform",
                    "reason": decision.reason,
                    "source": source,
                    "metadata": decision.metadata,
                }
            )
        entry = self.memory.add_experience(
            decision.text, affect_hint=affect_hint, importance=importance, source=source
        )
        if decision.decision != "allow":
            entry["safety"] = {
                "decision": decision.decision,
                "reason": decision.reason,
                "metadata": decision.metadata,
            }
        activation = ModuleActivation(
            module_name="memory",
            task_goal="observation",
            confidence=1.0,
            outcome=decision.text,
            tags={"observation"},
        )
        self.cognitive_map.record_activation(activation)
        self._history.append(activation)
        return entry

    def recall(self, query: str, k: int = 5) -> List[Dict[str, object]]:
        if not self._booted:
            self.boot()
        return self.memory.retrieve(query, k=k)

    def last_activations(self, limit: int = 10) -> List[ModuleActivation]:
        return self._history[-limit:]

    def cognitive_snapshot(self) -> Dict[str, Dict[str, float]]:
        return self.cognitive_map.snapshot()

    def module_relations(self, module_name: str, limit: Optional[int] = None) -> List[Dict[str, float]]:
        return self.cognitive_map.co_activations(module_name, limit=limit)

    def preview_observation(self, text: str) -> ObservationDecision:
        return self.policy.evaluate_observation(text)

    def safety_log(self, limit: int = 20) -> List[Dict[str, object]]:
        return self._safety_log[-limit:]

    def _log_safety_event(self, event: Dict[str, object]) -> None:
        self._safety_log.append(event)
        if len(self._safety_log) > 200:
            self._safety_log = self._safety_log[-200:]
