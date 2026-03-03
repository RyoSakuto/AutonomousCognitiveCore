from __future__ import annotations

from dataclasses import dataclass

from .state import StateSnapshot


@dataclass
class GeneratedGoal:
    description: str
    source: str
    priority: float


class IntrinsicGoalGenerator:
    def generate(
        self,
        snapshot: StateSnapshot,
        open_goals: list[dict],
        uncertainty_threshold: float,
        conflict_threshold: float,
        novelty_threshold: float,
    ) -> list[GeneratedGoal]:
        existing = " | ".join(g["description"].lower() for g in open_goals)
        out: list[GeneratedGoal] = []

        if snapshot.uncertainty >= uncertainty_threshold and "uncertainty" not in existing:
            out.append(
                GeneratedGoal(
                    description="Reduce uncertainty in current self-model assumptions",
                    source="intrinsic:uncertainty",
                    priority=min(1.0, snapshot.uncertainty + 0.1),
                )
            )

        if snapshot.conflict >= conflict_threshold and "conflict" not in existing:
            out.append(
                GeneratedGoal(
                    description="Resolve internal goal conflict and align priorities",
                    source="intrinsic:conflict",
                    priority=min(1.0, snapshot.conflict + 0.12),
                )
            )

        if snapshot.novelty >= novelty_threshold and "explore" not in existing:
            out.append(
                GeneratedGoal(
                    description="Explore an alternative strategy for long-term stability",
                    source="intrinsic:novelty",
                    priority=min(1.0, snapshot.novelty + 0.05),
                )
            )

        if not out and snapshot.tension < 0.45 and not open_goals and snapshot.cycle % 3 == 1:
            out.append(
                GeneratedGoal(
                    description="Perform coherence maintenance pass on internal model",
                    source="intrinsic:maintenance",
                    priority=0.40,
                )
            )

        return out
