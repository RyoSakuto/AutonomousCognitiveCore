from __future__ import annotations

from collections import Counter
from typing import Dict

from core.domain import TaskSpec
from modules.base import ModuleResult, NeuroModule


class AffectSensingModule(NeuroModule):
    name = "affect_sensing"
    capabilities = frozenset({"affect", "observation"})
    priority = 1.0

    POSITIVE = {"freude", "stolz", "erfolg", "gut", "glücklich", "erleichtert"}
    NEGATIVE = {"fehler", "verlust", "traurig", "ärger", "kritisch", "problem", "schmerz"}

    def run(self, task: TaskSpec, context) -> ModuleResult:
        text = task.payload.get("text", "")
        tokens = [tok.strip(".,!?").lower() for tok in text.split()]
        counts = Counter(tokens)
        pos_hits = sum(counts[w] for w in self.POSITIVE if w in counts)
        neg_hits = sum(counts[w] for w in self.NEGATIVE if w in counts)
        total_hits = max(pos_hits + neg_hits, 1)
        valenz = (pos_hits - neg_hits) / total_hits
        arousal = min(1.0, abs(pos_hits - neg_hits) / total_hits)
        affect = {"valenz": valenz, "arousal": arousal}
        follow_up = {"memory": {"text": text, "affect": affect}}
        traces: Dict[str, float] = {"valenz": valenz, "arousal": arousal}
        return ModuleResult(output=affect, confidence=0.7, traces=traces, follow_up=follow_up)
