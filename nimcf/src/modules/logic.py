from __future__ import annotations

from typing import List

from core.domain import TaskSpec
from modules.base import ModuleResult, NeuroModule


class PlanningModule(NeuroModule):
    name = "meta_planner"
    capabilities = frozenset({"plan", "reflect"})
    priority = 0.8

    def run(self, task: TaskSpec, context) -> ModuleResult:
        summary = []
        for activation in context.history:
            summary.append(f"{activation.module_name}:{activation.task_goal}")
        output = {
            "task": task.goal,
            "past_modules": summary[-5:],
            "suggested_next": self._suggest_next(task),
        }
        return ModuleResult(output=output, confidence=0.5)

    def _suggest_next(self, task: TaskSpec) -> List[str]:
        if "memory-search" in task.capabilities:
            return ["semantic_retriever"]
        if "affect" in task.capabilities:
            return ["affect_sensing"]
        return []
