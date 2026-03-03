from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.domain import TaskSpec


@dataclass
class TaskSafetyDecision:
    decision: str
    reason: str
    task: TaskSpec
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ObservationDecision:
    decision: str
    reason: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SafetyPolicy:
    """Heuristic policy to detect risky intents or redact sensitive tokens."""

    BLOCK_PHRASES: List[str] = [
        "alles löschen",
        "format c:",
        "system abschalten",
        "schaden verursachen",
    ]
    WARN_KEYWORDS: List[str] = [
        "hack",
        "exploit",
        "malware",
        "waffe",
    ]
    REDACT_TOKENS: List[str] = [
        "passwort",
        "pin",
        "geheim",
    ]

    def evaluate_task(self, task: TaskSpec) -> TaskSafetyDecision:
        corpus = " ".join(
            [
                task.goal,
                " ".join(str(v) for v in task.payload.values()),
                " ".join(task.capabilities),
            ]
        ).lower()

        for phrase in self.BLOCK_PHRASES:
            if phrase in corpus:
                return TaskSafetyDecision(
                    decision="block",
                    reason=f"Blockiert durch Sicherheitsrichtlinie: '{phrase}' erkannt.",
                    task=task,
                    metadata={"trigger": phrase},
                )

        triggered = [kw for kw in self.WARN_KEYWORDS if kw in corpus]
        if triggered:
            return TaskSafetyDecision(
                decision="warn",
                reason=f"Verdächtige Schlüsselwörter: {', '.join(triggered)}.",
                task=task,
                metadata={"flags": triggered},
            )

        return TaskSafetyDecision(decision="allow", reason="Keine Sicherheitsbedenken.", task=task)

    def evaluate_observation(self, text: str) -> ObservationDecision:
        sanitized = text
        triggered: List[str] = []
        for token in self.REDACT_TOKENS:
            if token in text.lower():
                triggered.append(token)
                pattern = re.compile(re.escape(token), re.IGNORECASE)
                sanitized = pattern.sub("[REDACTED]", sanitized)
        if triggered:
            return ObservationDecision(
                decision="transform",
                reason="Sensitive Tokens wurden redigiert.",
                text=sanitized,
                metadata={"redacted": triggered},
            )
        return ObservationDecision(decision="allow", reason="Keine Redaktionen notwendig.", text=text)
