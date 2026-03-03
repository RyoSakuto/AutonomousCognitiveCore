from __future__ import annotations

import random


class ExplorationEngine:
    def __init__(self, exploration_factor: float, seed: int = 23) -> None:
        self.exploration_factor = exploration_factor
        self._rng = random.Random(seed)

    def should_branch(self, decision: str, confidence: float, exploration_factor: float) -> bool:
        if decision == "explore":
            return True
        if confidence < 0.65:
            return self._rng.random() < exploration_factor
        return self._rng.random() < (exploration_factor * 0.4)

    def branch_hypothesis(self, hypothesis: str) -> str:
        return (
            "Counterfactual branch: invert one central assumption and test if the same "
            "goal can be achieved with fewer conflicts. Base hypothesis: "
            f"{hypothesis}"
        )
