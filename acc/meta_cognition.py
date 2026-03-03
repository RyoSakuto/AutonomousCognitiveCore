from __future__ import annotations

import random
from dataclasses import dataclass

from .state import StateSnapshot


@dataclass
class Evaluation:
    confidence: float
    weaknesses: list[str]
    decision: str


class MetaCognition:
    def __init__(self, seed: int = 13) -> None:
        self._rng = random.Random(seed)

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    def evaluate(self, snapshot: StateSnapshot, goal_priority: float) -> Evaluation:
        confidence = self._clamp01(
            0.74
            - 0.30 * snapshot.uncertainty
            - 0.22 * snapshot.conflict
            + 0.24 * goal_priority
            + self._rng.uniform(-0.08, 0.08)
        )

        weaknesses: list[str] = []
        if snapshot.uncertainty > 0.65:
            weaknesses.append("assumptions_not_validated")
        if snapshot.conflict > 0.58:
            weaknesses.append("goal_tradeoff_unclear")
        if snapshot.novelty > 0.72:
            weaknesses.append("exploration_debt")
        if not weaknesses:
            weaknesses.append("none_critical")

        decision = "commit" if confidence >= 0.55 else "explore"
        return Evaluation(confidence=confidence, weaknesses=weaknesses, decision=decision)
