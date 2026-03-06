from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .llm import LLMClient


@dataclass
class PlannedTask:
    key: str
    title: str
    description: str
    status: str
    priority: float
    depends_on: list[str]
    worker: str | None
    acceptance_criteria: list[str]


@dataclass
class PlannedGoal:
    plan_title: str
    summary: str
    tasks: list[PlannedTask]
    fallback: bool
    raw_excerpt: str


class GoalToPlanPlanner:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _normalize_status(value: str, default: str = "creative") -> str:
        token = value.strip().lower()
        if token in {"idea", "creative", "queued"}:
            return token
        return default

    @staticmethod
    def _normalize_worker(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        token = value.strip().lower()
        aliases = {
            "acc": "acc",
            "core": "acc",
            "nimcf": "nimcf",
            "nim": "nimcf",
            "kidiekiruft": "kidiekiruft",
            "orchestrator": "kidiekiruft",
            "ki_die_ki_ruft": "kidiekiruft",
        }
        return aliases.get(token)

    @staticmethod
    def _slug(text: str) -> str:
        token = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
        token = token.strip("-")
        return token[:24] or "task"

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _is_fallback_text(text: str) -> bool:
        lower = text.lower()
        return (
            text.startswith("Heuristic proposal:")
            or "fallback:" in lower
            or "endpoint unavailable" in lower
            or "unavailable (" in lower
        )

    def _heuristic_plan(self, goal_text: str, default_status: str, base_priority: float) -> PlannedGoal:
        clean = goal_text.strip().replace("\n", " ")
        short = clean[:140] or "Neues Ziel"
        title = f"Plan fuer: {short}"

        discovery_worker = None
        implementation_worker = None
        lower = clean.lower()
        if any(token in lower for token in ("memory", "kontext", "retrieval", "semantik")):
            implementation_worker = "nimcf"
        if any(token in lower for token in ("delegation", "dispatch", "workflow", "orchestrator")):
            implementation_worker = "kidiekiruft"

        tasks = [
            PlannedTask(
                key="scope",
                title="Ziel schaerfen und Akzeptanzkriterien festlegen",
                description=(
                    f"Projektziel: {short}\n"
                    "Arbeite das Ziel in umsetzbare Anforderungen aus, formuliere Akzeptanzkriterien, "
                    "Risiken und eine klare Done-Definition."
                ),
                status=self._normalize_status(default_status, "creative"),
                priority=min(1.0, base_priority + 0.08),
                depends_on=[],
                worker=discovery_worker,
                acceptance_criteria=[
                    "Ziel ist in klaren Arbeitspaketen beschrieben",
                    "Akzeptanzkriterien sind explizit festgehalten",
                    "Risiken und offene Fragen sind benannt",
                ],
            ),
            PlannedTask(
                key="build",
                title=f"Kernumsetzung fuer: {short[:96]}",
                description=(
                    f"Setze den Hauptteil des Ziels um: {short}.\n"
                    "Nutze den Scope-Task als Grundlage und arbeite nur den Kernnutzen ab."
                ),
                status="queued",
                priority=base_priority,
                depends_on=["scope"],
                worker=implementation_worker,
                acceptance_criteria=[
                    "Kernfunktion ist umgesetzt",
                    "Ergebnis ist nachvollziehbar dokumentiert",
                ],
            ),
            PlannedTask(
                key="validate",
                title="Validierung, Test und Doku abschliessen",
                description=(
                    "Pruefe das Ergebnis gegen Akzeptanzkriterien, ergaenze Tests und aktualisiere die Doku."
                ),
                status="queued",
                priority=max(0.45, base_priority - 0.04),
                depends_on=["build"],
                worker="acc",
                acceptance_criteria=[
                    "Tests oder Plausibilitaetschecks sind dokumentiert",
                    "Doku oder Runbook wurde aktualisiert",
                    "Abschlusszustand ist nachvollziehbar",
                ],
            ),
        ]
        return PlannedGoal(
            plan_title=title,
            summary="Heuristischer 3-Schritt-Plan aus Scope, Umsetzung und Validierung.",
            tasks=tasks,
            fallback=True,
            raw_excerpt="heuristic_goal_plan",
        )

    def plan_goal(self, goal_text: str, default_status: str = "creative", base_priority: float = 0.82) -> PlannedGoal:
        normalized_status = self._normalize_status(default_status, "creative")
        clamped_priority = max(0.0, min(1.0, float(base_priority)))
        prompt = (
            "Erzeuge aus dem folgenden Ziel einen kleinen, realistischen Task-Plan auf Deutsch.\n"
            "Antworte NUR als JSON mit den Keys: plan_title, summary, tasks.\n"
            "tasks muss eine Liste von Objekten mit Keys enthalten: key, title, description, status, priority, depends_on, worker, acceptance_criteria.\n"
            "Erlaubte status-Werte: idea, creative, queued.\n"
            "Erlaubte worker-Werte: acc, nimcf, kidiekiruft oder leer.\n"
            "Erzeuge 2 bis 5 Tasks, in einer sinnvollen Reihenfolge mit Dependencies ueber depends_on (Liste von task keys).\n"
            f"default_status={normalized_status}\n"
            f"base_priority={clamped_priority:.2f}\n"
            f"goal={goal_text.strip()}"
        )
        raw = self.llm.generate(prompt)
        data = self._extract_json_object(raw)
        fallback = self._is_fallback_text(raw) or data is None
        if data is None:
            return self._heuristic_plan(goal_text, normalized_status, clamped_priority)

        plan_title = str(data.get("plan_title") or f"Plan fuer: {goal_text[:120]}").strip()[:180]
        summary = str(data.get("summary") or "Autogenerierter Task-Plan.").strip()[:700]
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return self._heuristic_plan(goal_text, normalized_status, clamped_priority)

        parsed_tasks: list[PlannedTask] = []
        seen_keys: set[str] = set()
        for index, item in enumerate(raw_tasks[:5], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            if not title or not description:
                continue

            key_value = str(item.get("key") or self._slug(title) or f"task-{index}").strip().lower()
            key_value = self._slug(key_value)
            if key_value in seen_keys:
                key_value = f"{key_value}-{index}"
            seen_keys.add(key_value)

            status = self._normalize_status(str(item.get("status") or normalized_status), normalized_status)
            try:
                priority = max(0.0, min(1.0, float(item.get("priority", clamped_priority))))
            except (TypeError, ValueError):
                priority = clamped_priority

            depends_on: list[str] = []
            raw_depends = item.get("depends_on")
            if isinstance(raw_depends, list):
                for dep in raw_depends:
                    if isinstance(dep, str) and dep.strip():
                        depends_on.append(self._slug(dep))

            acceptance_criteria: list[str] = []
            raw_acceptance = item.get("acceptance_criteria")
            if isinstance(raw_acceptance, list):
                for criterion in raw_acceptance[:6]:
                    if isinstance(criterion, str) and criterion.strip():
                        acceptance_criteria.append(criterion.strip()[:220])

            parsed_tasks.append(
                PlannedTask(
                    key=key_value,
                    title=title[:180],
                    description=description[:1400],
                    status=status,
                    priority=priority,
                    depends_on=depends_on,
                    worker=self._normalize_worker(item.get("worker")),
                    acceptance_criteria=acceptance_criteria,
                )
            )

        if not parsed_tasks:
            return self._heuristic_plan(goal_text, normalized_status, clamped_priority)

        valid_keys = {task.key for task in parsed_tasks}
        for task in parsed_tasks:
            task.depends_on = [dep for dep in task.depends_on if dep in valid_keys and dep != task.key]

        return PlannedGoal(
            plan_title=plan_title,
            summary=summary,
            tasks=parsed_tasks,
            fallback=fallback,
            raw_excerpt=raw.strip()[:500],
        )
