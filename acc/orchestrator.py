from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ACCConfig
from .db import ACCDatabase
from .embedding import build_embedder
from .exploration import ExplorationEngine
from .goal_generator import IntrinsicGoalGenerator
from .llm import build_llm_client
from .memory import RetrievedMemory, SemanticMemory
from .meta_cognition import MetaCognition
from .self_modification import RuntimePolicy, SelfModificationManager
from .state import StateStore


@dataclass
class RunSummary:
    cycles: int
    start_cycle: int
    end_cycle: int
    autonomous_tasks: int
    avg_uncertainty: float
    db_path: str


class ACCOrchestrator:
    MODE_WORKER_BASELINE = {
        "discovery": {"acc", "nimcf", "kidiekiruft"},
        "balanced": {"acc", "nimcf", "kidiekiruft"},
        "guarded": {"acc", "nimcf"},
        "production": {"acc"},
    }

    def __init__(self, config: ACCConfig) -> None:
        self.config = config
        self.db = ACCDatabase(config.db_path)
        self.db.ensure_schema()

        self.state = StateStore(self.db)
        self.goal_generator = IntrinsicGoalGenerator()
        self.meta = MetaCognition()
        self.exploration = ExplorationEngine(config.exploration_factor)
        self.llm = build_llm_client(config)
        self.embedder = build_embedder(config)
        self.memory = SemanticMemory(
            db=self.db,
            embedder=self.embedder,
            candidate_window=config.memory_candidate_window,
        )
        self.self_mod = SelfModificationManager(self.state, config)
        self.policy: RuntimePolicy = self.self_mod.bootstrap()
        self._nimcf_booted = False

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _format_memories(memories: list[RetrievedMemory]) -> str:
        if not memories:
            return "Relevant memories: none"
        lines = []
        for item in memories:
            score = f"{item.score:.2f}"
            snippet = item.text.replace("\n", " ").strip()[:160]
            lines.append(f"- score={score} source={item.source_kind}:{item.source_id} text={snippet}")
        return "Relevant memories:\n" + "\n".join(lines)

    def _build_prompt(
        self,
        goal: dict,
        snapshot,
        self_model: dict[str, str],
        memories: list[RetrievedMemory],
    ) -> str:
        memory_block = self._format_memories(memories)
        return (
            f"Goal: {goal['description']}\n"
            f"Priority: {goal['priority']:.2f}\n"
            f"State: uncertainty={snapshot.uncertainty:.2f}, "
            f"conflict={snapshot.conflict:.2f}, novelty={snapshot.novelty:.2f}, "
            f"tension={snapshot.tension:.2f}\n"
            f"Self-model strategy: {self_model.get('strategy', 'unknown')}\n"
            f"{memory_block}\n"
            "Provide one concise actionable hypothesis to progress this goal."
        )

    @staticmethod
    def _deterministic_external_response(
        user_text: str,
        hypotheses: list[dict],
        goal_status: str | None,
    ) -> str:
        question = user_text.strip().lower()
        if "was passiert" in question and "frage" in question:
            return (
                "Wenn du eine Frage stellst, nehme ich sie als externes Ziel auf, "
                "speichere sie im Dialogspeicher, verarbeite mehrere Denkzyklen "
                "und antworte danach auf Basis meiner internen Hypothesen. "
                "Wenn kein LLM verfuegbar ist, antworte ich mit einer stabilen Heuristik."
            )

        if not hypotheses:
            return (
                "Ich habe deine Anfrage aufgenommen, aber aktuell noch zu wenig interne "
                "Signale fuer eine belastbare Antwort. Gib mir bitte mehr Zyklen."
            )

        best = hypotheses[0]
        confidence = float(best.get("confidence", 0.0))
        best_text = str(best.get("text", "")).replace("\n", " ").strip()
        if best_text.startswith("Heuristic proposal:"):
            best_text = (
                "starte mit einer klar abgegrenzten Teilaufgabe, pruefe die wichtigsten "
                "Annahmen und entscheide dann den naechsten Schritt"
            )
        if "fallback:" in best_text.lower() or "endpoint unavailable" in best_text.lower():
            best_text = (
                "arbeite erst die kritischsten Unsicherheiten ab und validiere danach "
                "die Konsistenz der Loesung"
            )
        return (
            f"Ich habe deine Anfrage verarbeitet (Goal-Status: {goal_status or 'unknown'}). "
            f"Mein aktueller Vorschlag ist: {best_text}. "
            f"Confidence: {confidence:.2f}."
        )

    @staticmethod
    def _is_fallback_text(text: str) -> bool:
        lower = text.lower()
        return (
            text.startswith("Heuristic proposal:")
            or "fallback:" in lower
            or "endpoint unavailable" in lower
            or "unavailable (" in lower
        )

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        raw = text[start : end + 1]
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    @staticmethod
    def _heuristic_creative_description(description: str) -> str:
        short = description.strip().replace("\n", " ")
        return (
            f"Creative exploration for: {short[:220]}\n"
            "- Brainstorm 3 implementation variants.\n"
            "- Compare risk, speed, and validation effort.\n"
            "- Define one concrete next execution step."
        )

    @staticmethod
    def _heuristic_ready_for_queue(text: str) -> bool:
        lower = text.lower()
        action_markers = (
            "implement",
            "build",
            "create",
            "write",
            "test",
            "analyze",
            "integrate",
            "refactor",
            "document",
            "fix",
        )
        return len(text.strip()) >= 60 and any(marker in lower for marker in action_markers)

    @staticmethod
    def _default_execution_ready_description(description: str) -> str:
        base = description.strip().replace("\n", " ")
        return (
            f"Ziel: {base[:240]}\n"
            "Scope: Implementierung, Logging, Validierung und Abschlussdokumentation.\n"
            "Nicht-Ziele: Architektur-Neubau oder unnoetige Plattformmigration.\n"
            "Umsetzungsschritte: 1) Anforderungen praezisieren 2) Umsetzung bauen "
            "3) Tests inkl. Edge-Cases ausfuehren 4) Ergebnisse dokumentieren.\n"
            "Akzeptanzkriterien: Funktionalitaet stabil, Logs nachvollziehbar, Tests gruen.\n"
            "Testplan: Unit-, Integrations- und End-to-End-Pruefung fuer Erfolg und Fehlerpfade.\n"
            "Artefakte: Code-Aenderung, Testbericht, kurzes Runbook-Update."
        )

    def _interpret_human_feedback(self, feedback: str) -> dict:
        text = feedback.strip()
        if not text:
            return {
                "intent": "none",
                "confidence": 1.0,
                "requires_clarification": False,
                "requires_rework": False,
                "rationale": "empty_feedback",
                "fallback": True,
            }

        prompt = (
            "Classify this human feedback for task gating.\n"
            "Return strict JSON with keys: intent, confidence, requires_clarification, "
            "requires_rework, rationale.\n"
            f"feedback={text}"
        )
        raw = self.llm.generate(prompt)
        data = self._extract_json_object(raw)
        fallback = self._is_fallback_text(raw) or data is None

        lower = text.lower()
        heuristic_clarification_markers = (
            "genauere beschreibung",
            "mehr details",
            "mehr detail",
            "mehr infos",
            "konkretisieren",
            "konkreter",
            "beschreibung",
            "details",
        )
        heuristic_rework_markers = (
            "rework",
            "nochmal",
            "nicht gut",
            "falsch",
            "ablehnen",
            "neu machen",
        )
        requires_clarification = any(marker in lower for marker in heuristic_clarification_markers)
        requires_rework = any(marker in lower for marker in heuristic_rework_markers)
        intent = "clarification_request" if requires_clarification else "generic_feedback"
        confidence = 0.68
        rationale = "heuristic_feedback_interpretation"

        if data is not None:
            if isinstance(data.get("intent"), str) and data["intent"].strip():
                intent = data["intent"].strip()[:80]
            if isinstance(data.get("confidence"), (int, float)):
                confidence = max(0.0, min(1.0, float(data["confidence"])))
            if isinstance(data.get("requires_clarification"), bool):
                requires_clarification = data["requires_clarification"]
            if isinstance(data.get("requires_rework"), bool):
                requires_rework = data["requires_rework"]
            if isinstance(data.get("rationale"), str) and data["rationale"].strip():
                rationale = data["rationale"].strip()[:300]

        return {
            "intent": intent,
            "confidence": confidence,
            "requires_clarification": requires_clarification,
            "requires_rework": requires_rework,
            "rationale": rationale,
            "fallback": fallback,
        }

    def _generate_clarified_task_brief(self, task: dict, feedback: str) -> dict:
        prompt = (
            "Erzeuge fuer den Task eine umsetzungsreife, praezise Beschreibung auf Deutsch.\n"
            "Antwortformat: NUR JSON mit keys: title, detailed_description, confidence.\n"
            "Die Beschreibung muss enthalten: Ziel, Scope, Nicht-Ziele, Umsetzungsschritte, "
            "Akzeptanzkriterien, Testplan, Artefakte.\n"
            f"Task-Title: {task['title']}\n"
            f"Task-Description: {task['description']}\n"
            f"Human-Feedback: {feedback.strip()}"
        )
        raw = self.llm.generate(prompt)
        data = self._extract_json_object(raw)
        fallback = self._is_fallback_text(raw) or data is None

        title = str(task["title"]).strip()
        description = self._default_execution_ready_description(str(task["description"]))
        confidence = 0.66

        if data is not None:
            if isinstance(data.get("title"), str) and data["title"].strip():
                title = data["title"].strip()[:180]
            if isinstance(data.get("detailed_description"), str) and data["detailed_description"].strip():
                description = data["detailed_description"].strip()[:3000]
            if isinstance(data.get("confidence"), (int, float)):
                confidence = max(0.0, min(1.0, float(data["confidence"])))

        return {
            "title": title,
            "description": description,
            "confidence": confidence,
            "fallback": fallback,
        }

    def _auto_handle_human_feedback(self, task_id: int, approved: bool, feedback: str, cycle: int) -> list[str]:
        actions: list[str] = []
        text = feedback.strip()
        if not text:
            return actions

        task = self.state.get_task(task_id)
        if task is None:
            return actions

        interpretation = self._interpret_human_feedback(text)
        self.state.add_task_review(
            task_id=task_id,
            reviewer="acc.feedback_interpreter",
            decision="feedback_interpreted",
            score=float(interpretation["confidence"]),
            feedback=str(interpretation["rationale"]),
            meta={
                "cycle": cycle,
                "intent": interpretation["intent"],
                "requires_clarification": interpretation["requires_clarification"],
                "requires_rework": interpretation["requires_rework"],
                "fallback": interpretation["fallback"],
            },
        )
        self.state.add_agent_event(
            cycle=cycle,
            event_type="task_human_feedback_interpreted",
            severity="info",
            message=f"task_id={task_id} intent={interpretation['intent']}",
            task_id=task_id,
            payload=interpretation,
        )

        if bool(interpretation["requires_clarification"]):
            brief = self._generate_clarified_task_brief(task, text)
            self.state.update_task_brief(
                task_id=task_id,
                title=str(brief["title"]),
                description=str(brief["description"]),
            )

            if approved:
                status = "queued"
                summary = "Auto-clarified after human approval."
                decision = "auto_clarified_for_execution"
            else:
                status = "creative"
                summary = "Auto-clarified while staying in creative stage."
                decision = "auto_clarified_for_rework"

            self.state.update_task_status(task_id=task_id, status=status, result_summary=summary)
            self.state.add_task_review(
                task_id=task_id,
                reviewer="acc.feedback_interpreter",
                decision=decision,
                score=float(brief["confidence"]),
                feedback="Taskbeschreibung automatisiert praezisiert.",
                meta={"cycle": cycle, "fallback": brief["fallback"]},
            )
            self.state.add_agent_event(
                cycle=cycle,
                event_type="task_auto_clarified",
                severity="info",
                message=f"task_id={task_id} status={status}",
                task_id=task_id,
                payload={"fallback": brief["fallback"], "confidence": brief["confidence"]},
            )
            actions.append("auto_clarified_description")

        if approved and bool(interpretation["requires_rework"]):
            self.state.add_agent_event(
                cycle=cycle,
                event_type="task_human_feedback_contradiction",
                severity="warning",
                message=f"task_id={task_id} approved but feedback suggests rework",
                task_id=task_id,
                payload=interpretation,
            )
            actions.append("contradiction_flagged")

        return actions

    @staticmethod
    def _normalize_execution_status(status: str) -> str:
        value = status.strip().lower()
        if value in {"done", "failed", "rework", "blocked"}:
            return value
        return "rework"

    @staticmethod
    def _normalize_followup_status(status: str) -> str:
        value = status.strip().lower()
        if value in {"idea", "creative", "queued"}:
            return value
        return "idea"

    @staticmethod
    def _parse_task_context(task: dict) -> dict:
        raw = task.get("context_json")
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _normalize_worker_name(value: str) -> str:
        token = value.strip().lower()
        aliases = {
            "acc": "acc",
            "core": "acc",
            "autonomouscognitivecore": "acc",
            "nimcf": "nimcf",
            "nim": "nimcf",
            "kidiekiruft": "kidiekiruft",
            "ki_die_ki_ruft": "kidiekiruft",
            "kidiruftki": "kidiekiruft",
            "kiruftki": "kidiekiruft",
            "orchestrator": "kidiekiruft",
        }
        return aliases.get(token, "acc")

    def _current_mode(self) -> str:
        mode = str(self.config.operating_mode or "").strip().lower()
        if mode in self.MODE_WORKER_BASELINE:
            return mode
        return "balanced"

    @staticmethod
    def _parse_csv_workers(raw: str) -> set[str]:
        values: set[str] = set()
        for token in str(raw or "").split(","):
            entry = token.strip().lower()
            if not entry:
                continue
            normalized = ACCOrchestrator._normalize_worker_name(entry)
            values.add(normalized)
        return values

    def _allowed_workers(self) -> set[str]:
        mode = self._current_mode()
        allowed = set(self.MODE_WORKER_BASELINE.get(mode, self.MODE_WORKER_BASELINE["balanced"]))
        explicit_allow = self._parse_csv_workers(self.config.worker_allowlist)
        explicit_deny = self._parse_csv_workers(self.config.worker_denylist)

        if explicit_allow:
            allowed = allowed.intersection(explicit_allow)
        if explicit_deny:
            allowed = {worker for worker in allowed if worker not in explicit_deny}
        return allowed if allowed else {"acc"}

    @staticmethod
    def _parse_json_text(value: object) -> dict:
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_worker_from_owner(owner: str) -> str:
        token = owner.strip().lower()
        if "." in token:
            token = token.split(".", 1)[0]
        return token

    @staticmethod
    def _extract_confidence_from_run(run: dict) -> float | None:
        metrics = ACCOrchestrator._parse_json_text(run.get("metrics_json"))
        if isinstance(metrics.get("confidence"), (int, float)):
            return max(0.0, min(1.0, float(metrics["confidence"])))
        output = ACCOrchestrator._parse_json_text(run.get("output_payload"))
        if isinstance(output.get("confidence"), (int, float)):
            return max(0.0, min(1.0, float(output["confidence"])))
        return None

    def _infer_hint_worker(self, task: dict) -> str | None:
        source = str(task.get("source", "")).lower()
        if source.startswith("nimcf:") or ":nimcf" in source:
            return "nimcf"
        if source.startswith("kidiekiruft:") or "kidiruftki" in source or "kiruftki" in source:
            return "kidiekiruft"

        title = str(task.get("title", "")).lower()
        if title.startswith("[nimcf]"):
            return "nimcf"
        if title.startswith("[kidiekiruft]"):
            return "kidiekiruft"
        return None

    def _worker_performance_scores(self, candidates: list[str]) -> dict[str, float]:
        unique = [name for name in candidates if name in {"acc", "nimcf", "kidiekiruft"}]
        if not unique:
            return {"acc": 0.5}

        runs = self.state.get_recent_task_runs(limit=max(20, int(self.config.worker_stats_window_runs)))
        running = self.state.list_tasks(status="running", limit=300)

        stats: dict[str, dict[str, float]] = {
            key: {"total": 0.0, "success": 0.0, "fallback": 0.0, "confidence": 0.0, "running": 0.0}
            for key in unique
        }

        for item in runs:
            metrics = self._parse_json_text(item.get("metrics_json"))
            stage = str(metrics.get("stage", "")).strip().lower()
            if stage and stage != "queued_execution":
                continue
            worker_name = self._normalize_worker_name(self._extract_worker_from_owner(str(item.get("worker", ""))))
            if worker_name not in stats:
                continue
            stats[worker_name]["total"] += 1.0
            run_status = str(item.get("status", "")).lower()
            if run_status == "succeeded":
                stats[worker_name]["success"] += 1.0
            if bool(metrics.get("fallback")):
                stats[worker_name]["fallback"] += 1.0
            conf = self._extract_confidence_from_run(item)
            if conf is not None:
                stats[worker_name]["confidence"] += conf

        for task in running:
            owner = str(task.get("owner", ""))
            worker_name = self._normalize_worker_name(self._extract_worker_from_owner(owner))
            if worker_name in stats:
                stats[worker_name]["running"] += 1.0

        scores: dict[str, float] = {}
        for worker_name, item in stats.items():
            total = item["total"]
            if total <= 0:
                scores[worker_name] = 0.46 - (item["running"] * 0.04)
                continue

            success_rate = item["success"] / total
            avg_conf = item["confidence"] / total if total > 0 else 0.55
            fallback_rate = item["fallback"] / total
            volume_bonus = min(0.08, total * 0.008)
            load_penalty = item["running"] * 0.05
            score = (
                (0.58 * success_rate)
                + (0.30 * avg_conf)
                + volume_bonus
                - (0.12 * fallback_rate)
                - load_penalty
            )
            scores[worker_name] = round(score, 4)
        return scores

    def _worker_candidates_for_task(self, task: dict) -> tuple[list[str], str | None]:
        context = self._parse_task_context(task)
        explicit = None
        for key in ("worker", "target_worker", "route", "executor"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                explicit = self._normalize_worker_name(value)
                break

        if explicit is not None:
            return [explicit], explicit

        candidates: list[str] = []
        raw_candidates = context.get("worker_candidates")
        if isinstance(raw_candidates, list):
            for entry in raw_candidates:
                if isinstance(entry, str) and entry.strip():
                    normalized = self._normalize_worker_name(entry)
                    if normalized not in candidates:
                        candidates.append(normalized)

        hint = self._infer_hint_worker(task)
        if hint is not None and hint not in candidates:
            candidates.insert(0, hint)

        if not candidates:
            candidates = ["acc", "nimcf", "kidiekiruft"]
        else:
            for fallback in ("acc", "nimcf", "kidiekiruft"):
                if fallback not in candidates:
                    candidates.append(fallback)
        return candidates, hint

    def _select_worker_for_task(
        self,
        task: dict,
    ) -> tuple[str, dict[str, float], str | None, dict[str, object]]:
        candidates, hint = self._worker_candidates_for_task(task)
        mode = self._current_mode()
        allowed_workers = self._allowed_workers()
        filtered_candidates = [name for name in candidates if name in allowed_workers]
        policy_meta = {
            "mode": mode,
            "allowed_workers": sorted(allowed_workers),
            "hint_denied": bool(hint is not None and hint not in allowed_workers),
        }
        if not filtered_candidates:
            filtered_candidates = [sorted(allowed_workers)[0]]

        if len(filtered_candidates) == 1:
            return filtered_candidates[0], {filtered_candidates[0]: 1.0}, hint, policy_meta

        scores = self._worker_performance_scores(filtered_candidates)
        if hint is not None and hint in scores:
            scores[hint] = round(scores[hint] + 0.06, 4)

        chosen = max(scores.items(), key=lambda item: item[1])[0]
        return chosen, scores, hint, policy_meta

    def _execute_task_payload_nimcf(self, task: dict) -> dict:
        root = Path(__file__).resolve().parent.parent / "nimcf"
        src_dir = root / "src"
        if not src_dir.exists():
            return {
                "status": "rework",
                "result_summary": "NIMCF source path not found.",
                "execution_notes": f"Missing path: {src_dir}",
                "confidence": 0.35,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": "",
            }

        src_text = str(src_dir)
        if src_text not in sys.path:
            sys.path.insert(0, src_text)

        try:
            from core.api import boot as nimcf_boot  # type: ignore
            from core.api import run_task as nimcf_run_task  # type: ignore
        except Exception as exc:
            return {
                "status": "rework",
                "result_summary": "NIMCF import failed.",
                "execution_notes": str(exc),
                "confidence": 0.34,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": str(exc),
            }

        if not self._nimcf_booted:
            try:
                nimcf_boot()
            except Exception:
                # Continue; run_task may still work depending on prior state.
                pass
            self._nimcf_booted = True

        try:
            result = nimcf_run_task(
                goal=str(task.get("title") or "task"),
                payload={"text": str(task.get("description", "")), "task_key": task.get("task_key")},
                capabilities=["plan", "memory-search", "reflect"],
            )
        except Exception as exc:
            return {
                "status": "failed",
                "result_summary": "NIMCF execution raised an exception.",
                "execution_notes": str(exc),
                "confidence": 0.25,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": str(exc),
            }

        status = "done"
        summary = "NIMCF processed task through its coordinator stack."
        confidence_values: list[float] = []
        if isinstance(result, list):
            for item in result:
                if not isinstance(item, dict):
                    continue
                output = item.get("output")
                if isinstance(output, dict) and output.get("status") == "blocked":
                    status = "blocked"
                    summary = "NIMCF safety policy blocked this task."
                conf = item.get("confidence")
                if isinstance(conf, (int, float)):
                    confidence_values.append(float(conf))
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.6
        notes = json.dumps(result, ensure_ascii=True)[:1200]
        return {
            "status": status,
            "result_summary": summary,
            "execution_notes": notes,
            "confidence": max(0.0, min(1.0, confidence)),
            "follow_up_tasks": [],
            "fallback": False,
            "raw_excerpt": notes[:500],
        }

    def _resolve_kidiekiruft_root(self) -> Path:
        configured = Path(self.config.kidiekiruft_root)
        if configured.is_absolute():
            return configured
        return (Path(__file__).resolve().parent.parent / configured).resolve()

    @staticmethod
    def _load_kidiekiruft_task(base: Path, task_id: str | None) -> dict | None:
        queue_file = base / "orchestrator" / "queue.json"
        if not queue_file.exists() or not task_id:
            return None
        try:
            data = json.loads(queue_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            return None
        for item in tasks:
            if isinstance(item, dict) and str(item.get("id")) == task_id:
                return item
        return None

    @staticmethod
    def _extract_kidiekiruft_task_id(stdout_text: str) -> str | None:
        task_match = re.search(r"Added\s+(TASK-\d+):", stdout_text or "")
        if not task_match:
            return None
        return task_match.group(1)

    def _execute_task_payload_kidiekiruft(self, task: dict) -> dict:
        base = self._resolve_kidiekiruft_root()
        script = base / "orchestrator.py"
        if not script.exists():
            return {
                "status": "rework",
                "result_summary": "KIdieKIruft orchestrator script not found.",
                "execution_notes": f"Missing script: {script}",
                "confidence": 0.33,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": "",
                "external_task_id": None,
                "external_status": None,
                "external_root": str(base),
                "live_dispatch": False,
            }

        live_dispatch = bool(self.config.kidiekiruft_live_dispatch_enabled)
        env = os.environ.copy()
        if self.config.kidiekiruft_worker_cmd.strip():
            env["WORKER_CMD"] = self.config.kidiekiruft_worker_cmd.strip()
        if self.config.kidiekiruft_worker_bin.strip():
            env["WORKER_BIN"] = self.config.kidiekiruft_worker_bin.strip()
        worker_timeout = max(10, int(self.config.kidiekiruft_worker_timeout_sec))
        env["WORKER_TIMEOUT_SECONDS"] = str(worker_timeout)

        if live_dispatch and not env.get("WORKER_CMD"):
            return {
                "status": "rework",
                "result_summary": "KIdieKIruft live dispatch blocked: WORKER_CMD is missing.",
                "execution_notes": (
                    "Set ACC_KIDIEKIRUFT_WORKER_CMD or use --kidiekiruft-worker-cmd "
                    "when enabling live dispatch."
                ),
                "confidence": 0.33,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": "",
            }

        add_cmd = [
            "python3",
            str(script),
            "task",
            "add",
            "--title",
            str(task.get("title", ""))[:140],
            "--description",
            str(task.get("description", ""))[:1000],
        ]
        try:
            add_res = subprocess.run(
                add_cmd,
                cwd=base,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                check=False,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "result_summary": "KIdieKIruft task-add call failed.",
                "execution_notes": str(exc),
                "confidence": 0.23,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": str(exc),
                "external_task_id": None,
                "external_status": None,
                "external_root": str(base),
                "live_dispatch": live_dispatch,
            }

        if add_res.returncode != 0:
            notes = (add_res.stdout or "") + "\n" + (add_res.stderr or "")
            return {
                "status": "failed",
                "result_summary": "KIdieKIruft task-add returned non-zero.",
                "execution_notes": notes[:1200],
                "confidence": 0.24,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": notes[:500],
                "external_task_id": None,
                "external_status": None,
                "external_root": str(base),
                "live_dispatch": live_dispatch,
            }

        kid_task_id = self._extract_kidiekiruft_task_id(add_res.stdout or "")

        dispatch_cmd = ["python3", str(script), "dispatch"]
        if kid_task_id:
            dispatch_cmd.extend(["--task-id", kid_task_id])
        if not live_dispatch:
            dispatch_cmd.append("--dry-run")
        dispatch_res = subprocess.run(
            dispatch_cmd,
            cwd=base,
            capture_output=True,
            text=True,
            timeout=worker_timeout + 30 if live_dispatch else 60,
            env=env,
            check=False,
        )
        notes = (
            f"task_add_stdout:\n{add_res.stdout}\n"
            f"task_add_stderr:\n{add_res.stderr}\n"
            f"dispatch_stdout:\n{dispatch_res.stdout}\n"
            f"dispatch_stderr:\n{dispatch_res.stderr}\n"
        )
        if dispatch_res.returncode != 0:
            return {
                "status": "rework",
                "result_summary": "KIdieKIruft dry-run dispatch failed; review delegation settings.",
                "execution_notes": notes[:1200],
                "confidence": 0.45,
                "follow_up_tasks": [],
                "fallback": True,
                "raw_excerpt": notes[:500],
                "external_task_id": kid_task_id,
                "external_status": None,
                "external_root": str(base),
                "live_dispatch": live_dispatch,
            }

        kid_task = self._load_kidiekiruft_task(base, kid_task_id)
        kid_status = str(kid_task.get("status")) if isinstance(kid_task, dict) else "unknown"
        if live_dispatch:
            if kid_status == "approved":
                status = "done"
                summary = "KIdieKIruft live dispatch completed and auto-review approved."
                confidence = 0.8
            elif kid_status == "rework":
                status = "rework"
                summary = "KIdieKIruft live dispatch completed but task requires rework."
                confidence = 0.54
            else:
                status = "blocked"
                summary = (
                    "KIdieKIruft live dispatch submitted task; waiting for downstream review completion."
                )
                confidence = 0.67
        else:
            status = "done"
            summary = "Delegation scaffold created via KIdieKIruft dry-run dispatch."
            confidence = 0.64

        return {
            "status": status,
            "result_summary": summary,
            "execution_notes": notes[:1200],
            "confidence": confidence,
            "follow_up_tasks": [],
            "fallback": not live_dispatch,
            "raw_excerpt": notes[:500],
            "external_task_id": kid_task_id,
            "external_status": kid_status,
            "external_root": str(base),
            "live_dispatch": live_dispatch,
        }

    def _execute_task_by_worker(self, task: dict, worker: str) -> dict:
        if worker == "nimcf":
            return self._execute_task_payload_nimcf(task)
        if worker == "kidiekiruft":
            return self._execute_task_payload_kidiekiruft(task)
        return self._execute_task_payload(task)

    @staticmethod
    def _extract_latest_kidiekiruft_review_note(external_task: dict) -> str:
        notes = external_task.get("review_notes")
        if not isinstance(notes, list) or not notes:
            return ""
        latest = notes[-1]
        if not isinstance(latest, dict):
            return ""
        text = latest.get("note")
        if isinstance(text, str):
            return text.strip()[:500]
        return ""

    @staticmethod
    def _read_json_file(path: Path) -> dict | list | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(data, (dict, list)):
            return data
        return None

    @staticmethod
    def _read_text_excerpt(path: Path, max_chars: int = 400) -> str:
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text.strip().replace("\n", " ")[:max_chars]

    def _collect_kidiekiruft_artifacts(self, base: Path, external_task: dict) -> dict:
        payload: dict[str, object] = {
            "kidiekiruft_attempts": external_task.get("attempts"),
            "kidiekiruft_updated_at": external_task.get("updated_at"),
            "kidiekiruft_acceptance_items": len(external_task.get("acceptance", []))
            if isinstance(external_task.get("acceptance"), list)
            else 0,
        }
        last_run = external_task.get("last_run")
        if not isinstance(last_run, str) or not last_run.strip():
            return payload

        run_rel = last_run.strip()
        run_dir = (base / run_rel).resolve()
        try:
            run_dir.relative_to(base.resolve())
        except ValueError:
            return payload
        payload["kidiekiruft_last_run"] = run_rel

        meta = self._read_json_file(run_dir / "meta.json")
        if isinstance(meta, dict):
            payload["kidiekiruft_meta"] = {
                "returncode": meta.get("returncode"),
                "effective_success": meta.get("effective_success"),
                "failure_reasons": meta.get("failure_reasons"),
                "started_at": meta.get("started_at"),
                "finished_at": meta.get("finished_at"),
            }

        followups = self._read_json_file(run_dir / "followup_tasks.json")
        if isinstance(followups, list):
            items: list[dict[str, str]] = []
            for entry in followups[:5]:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title", "")).strip()
                description = str(entry.get("description", "")).strip()
                if not title:
                    continue
                items.append({"title": title[:120], "description": description[:240]})
            payload["kidiekiruft_followups"] = items

        stdout_excerpt = self._read_text_excerpt(run_dir / "stdout.log")
        if stdout_excerpt:
            payload["kidiekiruft_stdout_excerpt"] = stdout_excerpt
        stderr_excerpt = self._read_text_excerpt(run_dir / "stderr.log")
        if stderr_excerpt:
            payload["kidiekiruft_stderr_excerpt"] = stderr_excerpt
        return payload

    @staticmethod
    def _rework_note_fingerprint(note: str) -> str:
        raw = note.strip().lower().encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()

    def _create_external_rework_followup(self, task: dict, review_note: str, cycle: int) -> int | None:
        note = review_note.strip()
        if not note:
            return None

        task_id = int(task["id"])
        context = self._parse_task_context(task)
        fingerprint = self._rework_note_fingerprint(note)
        if context.get("kidiekiruft_last_rework_fingerprint") == fingerprint:
            return None

        priority = min(1.0, max(0.0, float(task.get("priority", 0.5)) + 0.04))
        followup_context = {
            "origin_task_id": task_id,
            "origin_task_key": task.get("task_key"),
            "worker": context.get("worker", "acc"),
            "generated_from_external_rework": True,
            "rework_fingerprint": fingerprint,
        }
        followup_id = self.state.create_task(
            title=f"Rework-Analyse: {str(task.get('title', '')).strip()[:130]}",
            description=(
                "Externe Rework-Notiz aus KIdieKIruft verarbeiten und Umsetzungsplan schaerfen.\n"
                f"Originaltask: {task.get('task_key')}\n"
                f"Rework-Notiz: {note[:700]}\n"
                "Erwartung: konkrete Korrekturschritte, Tests, Abschlusskriterien."
            ),
            source=f"acc.sync:kidiekiruft_rework:{task.get('task_key')}",
            status="creative",
            priority=priority,
            parent_task_id=task_id,
            context=followup_context,
        )
        self.state.add_task_dependency(
            task_id=task_id,
            depends_on_task_id=followup_id,
            dependency_type="hard",
        )
        self.state.update_task_context(
            task_id=task_id,
            context={
                "kidiekiruft_last_rework_fingerprint": fingerprint,
                "kidiekiruft_last_rework_followup_id": followup_id,
            },
            merge=True,
        )
        self.state.add_agent_event(
            cycle=cycle,
            event_type="task_external_rework_followup_created",
            severity="warning",
            message=f"task_id={task_id} followup_id={followup_id}",
            task_id=followup_id,
            payload={"origin_task_id": task_id, "rework_note": note[:300]},
        )
        return followup_id

    def process_kidiekiruft_sync(self, cycle: int | None = None) -> int:
        effective_cycle = cycle if cycle is not None else max(1, self.state.next_cycle_number())
        synced = 0
        base = self._resolve_kidiekiruft_root()

        blocked_tasks = self.state.list_tasks(status="blocked", limit=500)
        for task in blocked_tasks:
            task_id = int(task["id"])
            context = self._parse_task_context(task)
            worker_hint = self._normalize_worker_name(str(context.get("worker", "")))
            owner = str(task.get("owner", ""))
            if worker_hint != "kidiekiruft" and not owner.startswith("kidiekiruft."):
                continue

            external_task_id = context.get("kidiekiruft_task_id")
            if not isinstance(external_task_id, str) or not external_task_id.strip():
                continue
            external_task_id = external_task_id.strip()

            external_task = self._load_kidiekiruft_task(base, external_task_id)
            if external_task is None:
                self.state.add_agent_event(
                    cycle=effective_cycle,
                    event_type="task_sync_missing_external",
                    severity="warning",
                    message=f"task_id={task_id} external_task={external_task_id} not found",
                    task_id=task_id,
                    payload={"external_task_id": external_task_id},
                )
                continue

            external_status = str(external_task.get("status", "")).lower()
            review_note = self._extract_latest_kidiekiruft_review_note(external_task)
            artifact_payload = self._collect_kidiekiruft_artifacts(base=base, external_task=external_task)
            self.state.update_task_context(
                task_id=task_id,
                context={
                    "kidiekiruft_external_status": external_status,
                    "kidiekiruft_last_sync_cycle": effective_cycle,
                    "kidiekiruft_last_review_note": review_note[:320],
                    **artifact_payload,
                },
                merge=True,
            )

            if external_status == "approved":
                summary = "Synced from KIdieKIruft: approved."
                if review_note:
                    summary = f"{summary} note={review_note}"
                self.state.update_task_status(task_id=task_id, status="done", result_summary=summary)
                self.state.add_task_review(
                    task_id=task_id,
                    reviewer="kidiekiruft.sync",
                    decision="sync_approved",
                    score=0.9,
                    feedback=review_note or "External review approved.",
                    meta={
                        "cycle": effective_cycle,
                        "external_task_id": external_task_id,
                        "external_status": external_status,
                        "artifacts": artifact_payload,
                    },
                )
                self.state.add_agent_event(
                    cycle=effective_cycle,
                    event_type="task_synced_from_kidiekiruft",
                    severity="info",
                    message=f"task_id={task_id} synced approved from {external_task_id}",
                    task_id=task_id,
                    payload={"external_task_id": external_task_id, "external_status": external_status},
                )
                self.state.add_episode(
                    cycle=effective_cycle,
                    kind="task_synced",
                    content=f"task_id={task_id} external={external_task_id} approved",
                    score=0.9,
                )
                synced += 1
            elif external_status == "rework":
                followup_id = None
                if self.config.task_external_rework_auto_requeue:
                    followup_id = self._create_external_rework_followup(
                        task=task,
                        review_note=review_note,
                        cycle=effective_cycle,
                    )
                    target_status = "queued"
                    decision = "sync_rework_requeued"
                    score = 0.62
                else:
                    target_status = "rework"
                    decision = "sync_rework"
                    score = 0.55

                summary = "Synced from KIdieKIruft: rework requested."
                if review_note:
                    summary = f"{summary} note={review_note}"
                if target_status == "queued":
                    summary = f"{summary} | auto_requeue=on"
                    if followup_id is not None:
                        summary = f"{summary} | followup={followup_id}"
                self.state.update_task_status(task_id=task_id, status=target_status, result_summary=summary)
                self.state.add_task_review(
                    task_id=task_id,
                    reviewer="kidiekiruft.sync",
                    decision=decision,
                    score=score,
                    feedback=review_note or "External review requested rework.",
                    meta={
                        "cycle": effective_cycle,
                        "external_task_id": external_task_id,
                        "external_status": external_status,
                        "auto_requeue": self.config.task_external_rework_auto_requeue,
                        "followup_id": followup_id,
                        "artifacts": artifact_payload,
                    },
                )
                self.state.add_agent_event(
                    cycle=effective_cycle,
                    event_type="task_synced_from_kidiekiruft",
                    severity="warning",
                    message=(
                        f"task_id={task_id} synced rework from {external_task_id} "
                        f"target_status={target_status}"
                    ),
                    task_id=task_id,
                    payload={
                        "external_task_id": external_task_id,
                        "external_status": external_status,
                        "target_status": target_status,
                        "followup_id": followup_id,
                    },
                )
                self.state.add_episode(
                    cycle=effective_cycle,
                    kind="task_synced",
                    content=(
                        f"task_id={task_id} external={external_task_id} "
                        f"rework target={target_status}"
                    ),
                    score=score,
                )
                synced += 1

        return synced

    def _execute_task_payload(self, task: dict) -> dict:
        description = str(task["description"]).strip()
        prompt = (
            "You are the ACC execution worker for queued tasks.\n"
            "Return strict JSON with keys: status, result_summary, execution_notes, confidence, follow_up_tasks.\n"
            "Allowed status: done, failed, rework, blocked.\n"
            "follow_up_tasks must be an array of objects with keys: title, description, status, priority.\n"
            f"task_key={task.get('task_key')}\n"
            f"title={task['title']}\n"
            f"description={description}\n"
            "Keep it realistic and concise."
        )
        raw = self.llm.generate(prompt)
        data = self._extract_json_object(raw)
        fallback = self._is_fallback_text(raw) or data is None

        # Conservative deterministic fallback for unavailable/slow model responses.
        low = description.lower()
        if len(description) < 40:
            status = "rework"
            result_summary = "Taskbeschreibung ist zu knapp und wurde fuer Rework markiert."
            execution_notes = "Bitte Scope, Akzeptanzkriterien und Testplan konkretisieren."
            confidence = 0.52
            followups: list[dict] = []
        elif any(marker in low for marker in ("todo", "unklar", "tbd", "??")):
            status = "rework"
            result_summary = "Task enthaelt unklare Platzhalter und braucht Nachschaerfung."
            execution_notes = "Unklare Anforderungen entfernt/konkretisiert erforderlich."
            confidence = 0.56
            followups = []
        else:
            status = "done"
            result_summary = (
                "Task wurde autonom verarbeitet: Umsetzungsplan, Validierungsschritte "
                "und Abschlusskriterien wurden dokumentiert."
            )
            execution_notes = (
                "Naechster Schritt: Ergebnisse gegen Akzeptanzkriterien pruefen und "
                "bei Bedarf in Teilaufgaben verfeinern."
            )
            confidence = 0.62
            followups = []

        if data is not None:
            if isinstance(data.get("status"), str) and data["status"].strip():
                status = self._normalize_execution_status(data["status"])
            if isinstance(data.get("result_summary"), str) and data["result_summary"].strip():
                result_summary = data["result_summary"].strip()[:500]
            if isinstance(data.get("execution_notes"), str) and data["execution_notes"].strip():
                execution_notes = data["execution_notes"].strip()[:1200]
            if isinstance(data.get("confidence"), (int, float)):
                confidence = max(0.0, min(1.0, float(data["confidence"])))
            if isinstance(data.get("follow_up_tasks"), list):
                parsed: list[dict] = []
                for item in data["follow_up_tasks"][:3]:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title")
                    desc = item.get("description")
                    if not isinstance(title, str) or not isinstance(desc, str):
                        continue
                    status_value = self._normalize_followup_status(str(item.get("status", "idea")))
                    priority = item.get("priority", 0.55)
                    try:
                        pr = max(0.0, min(1.0, float(priority)))
                    except (TypeError, ValueError):
                        pr = 0.55
                    parsed.append(
                        {
                            "title": title.strip()[:180],
                            "description": desc.strip()[:1200],
                            "status": status_value,
                            "priority": pr,
                        }
                    )
                followups = parsed

        return {
            "status": self._normalize_execution_status(status),
            "result_summary": result_summary,
            "execution_notes": execution_notes,
            "confidence": confidence,
            "follow_up_tasks": followups,
            "fallback": fallback,
            "raw_excerpt": raw.strip()[:500],
        }

    def _create_followup_tasks(self, task: dict, execution: dict, cycle: int) -> list[int]:
        followups = execution.get("follow_up_tasks")
        if not isinstance(followups, list) or not followups:
            return []

        created_ids: list[int] = []
        parent_id = int(task["id"])
        task_key = str(task.get("task_key") or f"TASK-{parent_id}")
        for item in followups:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            description = str(item.get("description", "")).strip()
            if not title or not description:
                continue
            status = self._normalize_followup_status(str(item.get("status", "idea")))
            try:
                priority = max(0.0, min(1.0, float(item.get("priority", 0.55))))
            except (TypeError, ValueError):
                priority = 0.55
            followup_id = self.state.create_task(
                title=title[:180],
                description=description[:1200],
                source=f"acc.executor:followup:{task_key}",
                status=status,
                priority=priority,
                parent_task_id=parent_id,
                context={"origin_task_key": task_key, "origin_cycle": cycle},
            )
            self.state.add_agent_event(
                cycle=cycle,
                event_type="task_followup_created",
                severity="info",
                message=f"followup task_id={followup_id} created from {task_key}",
                task_id=followup_id,
                payload={"origin_task_id": parent_id, "origin_task_key": task_key},
            )
            created_ids.append(followup_id)
        return created_ids

    @staticmethod
    def _parse_iso_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _task_retry_policy(self, task: dict) -> dict:
        context = self._parse_task_context(task)
        max_retries = context.get("max_retries", self.config.task_retry_default_max_retries)
        backoff = context.get("retry_backoff_sec", self.config.task_retry_default_backoff_sec)
        retry_count = context.get("retry_count", 0)
        retry_on = context.get("retry_on_statuses", ["failed", "rework"])

        try:
            max_retries_n = max(0, int(max_retries))
        except (TypeError, ValueError):
            max_retries_n = max(0, int(self.config.task_retry_default_max_retries))
        try:
            backoff_n = max(0, int(backoff))
        except (TypeError, ValueError):
            backoff_n = max(0, int(self.config.task_retry_default_backoff_sec))
        try:
            retry_count_n = max(0, int(retry_count))
        except (TypeError, ValueError):
            retry_count_n = 0

        normalized_retry_on: list[str] = []
        if isinstance(retry_on, list):
            for entry in retry_on:
                if isinstance(entry, str) and entry.strip():
                    normalized_retry_on.append(entry.strip().lower())
        if not normalized_retry_on:
            normalized_retry_on = ["failed", "rework"]

        return {
            "max_retries": max_retries_n,
            "retry_backoff_sec": backoff_n,
            "retry_count": retry_count_n,
            "retry_on_statuses": normalized_retry_on,
            "next_retry_at": context.get("next_retry_at"),
        }

    def _can_attempt_task_now(self, task: dict) -> tuple[bool, str, dict]:
        context = self._parse_task_context(task)
        task_id = int(task["id"])

        if self.config.task_dependency_enforcement:
            unmet = self.state.list_unmet_task_dependencies(task_id=task_id)
            if unmet:
                signature = ",".join(
                    f"{int(dep.get('depends_on_task_id', 0))}:{str(dep.get('depends_on_status', 'unknown'))}"
                    for dep in unmet
                )
                if str(context.get("dependency_wait_signature", "")) != signature:
                    self.state.update_task_context(
                        task_id=task_id,
                        context={
                            "dependency_wait_signature": signature[:240],
                            "dependency_wait_count": len(unmet),
                            "dependency_wait_updated_at": self._now_iso(),
                        },
                        merge=True,
                    )
                return False, "dependencies", {"unmet_dependencies": unmet}

        retry_policy = self._task_retry_policy(task)
        retry_ready_at = self._parse_iso_datetime(retry_policy.get("next_retry_at"))
        if retry_ready_at is not None and datetime.now(timezone.utc) < retry_ready_at:
            return False, "retry_backoff", {"next_retry_at": retry_ready_at.isoformat(timespec="seconds")}

        return True, "ready", {"retry_policy": retry_policy}

    def _apply_retry_strategy(
        self,
        task: dict,
        status: str,
        summary: str,
        notes: str,
        cycle: int,
    ) -> tuple[str, str, dict]:
        normalized = self._normalize_execution_status(status)
        policy = self._task_retry_policy(task)
        retry_on: list[str] = policy["retry_on_statuses"]
        retry_count = int(policy["retry_count"])
        max_retries = int(policy["max_retries"])
        backoff_sec = int(policy["retry_backoff_sec"])

        if normalized not in retry_on:
            return normalized, summary, {"retry_scheduled": False}
        if retry_count >= max_retries:
            return normalized, summary, {"retry_scheduled": False, "retry_exhausted": True}

        next_retry_count = retry_count + 1
        wait_seconds = backoff_sec * next_retry_count
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
        retry_summary = (
            f"{summary} | retry_scheduled={next_retry_count}/{max_retries}"
            f" wait={wait_seconds}s"
        )
        self.state.update_task_context(
            task_id=int(task["id"]),
            context={
                "retry_count": next_retry_count,
                "max_retries": max_retries,
                "retry_backoff_sec": backoff_sec,
                "retry_on_statuses": retry_on,
                "next_retry_at": next_retry_at.isoformat(timespec="seconds"),
                "last_retry_reason_status": normalized,
                "last_retry_cycle": cycle,
            },
            merge=True,
        )
        return "queued", retry_summary, {
            "retry_scheduled": True,
            "retry_count": next_retry_count,
            "max_retries": max_retries,
            "next_retry_at": next_retry_at.isoformat(timespec="seconds"),
            "last_status": normalized,
            "notes_excerpt": notes[:180],
        }

    def process_task_execution(self, cycle: int | None = None) -> int:
        effective_cycle = cycle if cycle is not None else max(1, self.state.next_cycle_number())
        executed = 0
        max_batch = max(1, int(self.config.task_execution_batch_size))

        candidates = self.state.list_tasks(status="queued", limit=max_batch * 8)
        for candidate in candidates:
            if executed >= max_batch:
                break
            task_id = int(candidate["id"])
            can_attempt, wait_reason, wait_meta = self._can_attempt_task_now(candidate)
            if not can_attempt:
                candidate_context = self._parse_task_context(candidate)
                if wait_reason == "dependencies":
                    unmet = wait_meta.get("unmet_dependencies", [])
                    signature = ",".join(
                        f"{int(dep.get('depends_on_task_id', 0))}:{str(dep.get('depends_on_status', 'unknown'))}"
                        for dep in unmet
                        if isinstance(dep, dict)
                    )
                    if signature and candidate_context.get("last_dependency_wait_notice") != signature:
                        self.state.update_task_context(
                            task_id=task_id,
                            context={"last_dependency_wait_notice": signature},
                            merge=True,
                        )
                        self.state.add_agent_event(
                            cycle=effective_cycle,
                            event_type="task_waiting_dependencies",
                            severity="info",
                            message=f"task_id={task_id} waiting for dependencies",
                            task_id=task_id,
                            payload={"signature": signature, "unmet": unmet},
                        )
                elif wait_reason == "retry_backoff":
                    next_retry_at = str(wait_meta.get("next_retry_at", ""))
                    if next_retry_at and candidate_context.get("last_retry_wait_notice") != next_retry_at:
                        self.state.update_task_context(
                            task_id=task_id,
                            context={"last_retry_wait_notice": next_retry_at},
                            merge=True,
                        )
                        self.state.add_agent_event(
                            cycle=effective_cycle,
                            event_type="task_retry_waiting",
                            severity="info",
                            message=f"task_id={task_id} backoff until {next_retry_at}",
                            task_id=task_id,
                            payload={"next_retry_at": next_retry_at},
                        )
                continue

            routed_worker, worker_scores, worker_hint, worker_policy = self._select_worker_for_task(
                candidate
            )
            worker_name = f"{routed_worker}.executor"
            task = self.state.claim_task(task_id=task_id, worker=worker_name)
            if task is None:
                continue

            if bool(worker_policy.get("hint_denied")):
                self.state.add_agent_event(
                    cycle=effective_cycle,
                    event_type="task_worker_policy_override",
                    severity="warning",
                    message=(
                        f"task_id={task_id} mode={worker_policy.get('mode')} "
                        f"hint={worker_hint} routed={routed_worker}"
                    ),
                    task_id=task_id,
                    payload={
                        "mode": worker_policy.get("mode"),
                        "worker_hint": worker_hint,
                        "routed_worker": routed_worker,
                        "allowed_workers": worker_policy.get("allowed_workers", []),
                    },
                )

            run_id = self.state.create_task_run(
                task_id=task_id,
                worker=worker_name,
                status="running",
                input_payload={
                    "task_id": task_id,
                    "task_key": task.get("task_key"),
                    "title": task["title"],
                    "description": task["description"],
                    "routed_worker": routed_worker,
                    "worker_hint": worker_hint,
                    "worker_scores": worker_scores,
                    "worker_policy": worker_policy,
                },
                metrics={
                    "stage": "queued_execution",
                    "cycle": effective_cycle,
                    "worker": routed_worker,
                    "worker_hint": worker_hint,
                    "worker_scores": worker_scores,
                    "worker_policy": worker_policy,
                },
            )
            try:
                execution = self._execute_task_by_worker(task, routed_worker)
                status = str(execution["status"])
                summary = str(execution["result_summary"])
                notes = str(execution["execution_notes"])
                confidence = float(execution["confidence"])
                external_task_id = execution.get("external_task_id")
                external_status = execution.get("external_status")
                external_root = execution.get("external_root")
                live_dispatch = bool(execution.get("live_dispatch", False))
                final_status = status
                final_summary = summary

                if isinstance(external_task_id, str) and external_task_id.strip():
                    self.state.update_task_context(
                        task_id=task_id,
                        context={
                            "worker": routed_worker,
                            "kidiekiruft_task_id": external_task_id.strip(),
                            "kidiekiruft_external_status": external_status,
                            "kidiekiruft_external_root": external_root,
                            "kidiekiruft_live_dispatch": live_dispatch,
                        },
                        merge=True,
                    )

                final_status, final_summary, retry_meta = self._apply_retry_strategy(
                    task=task,
                    status=status,
                    summary=summary,
                    notes=notes,
                    cycle=effective_cycle,
                )
                self.state.update_task_status(
                    task_id=task_id,
                    status=final_status,
                    result_summary=final_summary,
                    error_text=notes if status == "failed" and final_status != "queued" else None,
                )
                if final_status != "queued":
                    self.state.update_task_context(task_id=task_id, context={"next_retry_at": None}, merge=True)

                followup_ids = self._create_followup_tasks(task, execution, effective_cycle)

                run_status = "failed" if status == "failed" else "succeeded"
                self.state.complete_task_run(
                    run_id=run_id,
                    status=run_status,
                    output_payload={
                        "status": status,
                        "final_status": final_status,
                        "summary": final_summary,
                        "notes": notes,
                        "confidence": confidence,
                        "followup_ids": followup_ids,
                        "fallback": execution["fallback"],
                        "external_task_id": external_task_id,
                        "external_status": external_status,
                        "live_dispatch": live_dispatch,
                        "retry": retry_meta,
                    },
                    stdout_log=notes,
                    stderr_log=notes if status == "failed" else None,
                    metrics={
                        "confidence": confidence,
                        "status": status,
                        "final_status": final_status,
                        "worker": routed_worker,
                        "fallback": execution["fallback"],
                        "followups": len(followup_ids),
                        "external_task_id": external_task_id,
                        "retry_scheduled": bool(retry_meta.get("retry_scheduled", False)),
                    },
                )

                self.state.add_task_review(
                    task_id=task_id,
                    run_id=run_id,
                    reviewer=worker_name,
                    decision=(
                        f"execution_{status}_retry_scheduled"
                        if bool(retry_meta.get("retry_scheduled", False))
                        else f"execution_{status}"
                    ),
                    score=confidence,
                    feedback=final_summary,
                    meta={
                        "cycle": effective_cycle,
                        "worker": routed_worker,
                        "fallback": execution["fallback"],
                        "followup_ids": followup_ids,
                        "external_task_id": external_task_id,
                        "worker_hint": worker_hint,
                        "worker_scores": worker_scores,
                        "worker_policy": worker_policy,
                        "retry": retry_meta,
                    },
                )
                self.state.add_agent_event(
                    cycle=effective_cycle,
                    event_type="task_executed",
                    severity="info" if status != "failed" else "warning",
                    message=(
                        f"task_id={task_id} worker={routed_worker} "
                        f"status={status} final={final_status}"
                    ),
                    task_id=task_id,
                    run_id=run_id,
                    payload={
                        "worker": routed_worker,
                        "status": status,
                        "final_status": final_status,
                        "confidence": confidence,
                        "fallback": execution["fallback"],
                        "followup_ids": followup_ids,
                        "external_task_id": external_task_id,
                        "worker_hint": worker_hint,
                        "worker_scores": worker_scores,
                        "worker_policy": worker_policy,
                        "retry": retry_meta,
                    },
                )
                if bool(retry_meta.get("retry_scheduled", False)):
                    self.state.add_agent_event(
                        cycle=effective_cycle,
                        event_type="task_retry_scheduled",
                        severity="warning" if status == "failed" else "info",
                        message=(
                            f"task_id={task_id} retry={retry_meta.get('retry_count')}/"
                            f"{retry_meta.get('max_retries')} next={retry_meta.get('next_retry_at')}"
                        ),
                        task_id=task_id,
                        run_id=run_id,
                        payload=retry_meta,
                    )
                self.state.add_episode(
                    cycle=effective_cycle,
                    kind="task_executed",
                    content=(
                        f"task_id={task_id} worker={routed_worker} "
                        f"status={status} final={final_status}"
                    ),
                    score=confidence,
                )
            except Exception as exc:
                exception_summary = "Execution worker failed unexpectedly."
                exception_notes = str(exc)
                final_status, final_summary, retry_meta = self._apply_retry_strategy(
                    task=task,
                    status="failed",
                    summary=exception_summary,
                    notes=exception_notes,
                    cycle=effective_cycle,
                )
                self.state.complete_task_run(
                    run_id=run_id,
                    status="failed",
                    stderr_log=str(exc),
                    metrics={
                        "stage": "queued_execution",
                        "failed": True,
                        "final_status": final_status,
                        "retry_scheduled": bool(retry_meta.get("retry_scheduled", False)),
                    },
                )
                self.state.update_task_status(
                    task_id=task_id,
                    status=final_status,
                    error_text=exception_notes if final_status != "queued" else None,
                    result_summary=final_summary,
                )
                if final_status != "queued":
                    self.state.update_task_context(task_id=task_id, context={"next_retry_at": None}, merge=True)
                self.state.add_agent_event(
                    cycle=effective_cycle,
                    event_type="task_execution_failed",
                    severity="warning",
                    message=(
                        f"task_id={task_id} worker={routed_worker} exception={exc} "
                        f"final={final_status}"
                    ),
                    task_id=task_id,
                    run_id=run_id,
                    payload={"worker": routed_worker, "retry": retry_meta, "final_status": final_status},
                )
                if bool(retry_meta.get("retry_scheduled", False)):
                    self.state.add_agent_event(
                        cycle=effective_cycle,
                        event_type="task_retry_scheduled",
                        severity="warning",
                        message=(
                            f"task_id={task_id} retry={retry_meta.get('retry_count')}/"
                            f"{retry_meta.get('max_retries')} next={retry_meta.get('next_retry_at')}"
                        ),
                        task_id=task_id,
                        run_id=run_id,
                        payload=retry_meta,
                    )
            executed += 1

        return executed

    def _process_idea_tasks(self, cycle: int) -> int:
        promoted = 0
        ideas = self.state.list_tasks(status="idea", limit=self.config.task_funnel_batch_size)
        for task in ideas:
            task_id = int(task["id"])
            run_id = self.state.create_task_run(
                task_id=task_id,
                worker="acc.idea_refiner",
                input_payload={
                    "task_id": task_id,
                    "task_key": task.get("task_key"),
                    "title": task["title"],
                    "description": task["description"],
                },
                status="running",
                metrics={"stage": "idea_to_creative"},
            )
            try:
                prompt = (
                    "Transform this idea task into a creative brainstorming task.\n"
                    "Return strict JSON with keys: title, creative_description, confidence, rationale.\n"
                    f"title={task['title']}\n"
                    f"description={task['description']}"
                )
                raw = self.llm.generate(prompt)
                data = self._extract_json_object(raw)
                fallback = self._is_fallback_text(raw) or data is None

                title = str(task["title"]).strip()
                creative_description = self._heuristic_creative_description(str(task["description"]))
                confidence = 0.45
                rationale = "fallback_heuristic"

                if data is not None:
                    if isinstance(data.get("title"), str) and data["title"].strip():
                        title = data["title"].strip()[:180]
                    if (
                        isinstance(data.get("creative_description"), str)
                        and data["creative_description"].strip()
                    ):
                        creative_description = data["creative_description"].strip()[:1200]
                    if isinstance(data.get("confidence"), (int, float)):
                        confidence = max(0.0, min(1.0, float(data["confidence"])))
                    if isinstance(data.get("rationale"), str) and data["rationale"].strip():
                        rationale = data["rationale"].strip()[:260]

                self.state.update_task_brief(task_id=task_id, title=title, description=creative_description)
                self.state.update_task_status(
                    task_id=task_id,
                    status="creative",
                    result_summary=f"Idea promoted to creative. rationale={rationale}",
                )
                self.state.complete_task_run(
                    run_id=run_id,
                    status="succeeded",
                    output_payload={
                        "status": "creative",
                        "title": title,
                        "creative_description": creative_description,
                        "confidence": confidence,
                        "fallback": fallback,
                    },
                    metrics={"fallback": fallback, "confidence": confidence},
                )
                self.state.add_task_review(
                    task_id=task_id,
                    run_id=run_id,
                    reviewer="acc.idea_refiner",
                    decision="promote_creative",
                    score=confidence,
                    feedback=rationale,
                    meta={"cycle": cycle, "fallback": fallback},
                )
                self.state.add_agent_event(
                    cycle=cycle,
                    event_type="task_promoted_idea_to_creative",
                    severity="info",
                    message=f"task_id={task_id} promoted to creative",
                    task_id=task_id,
                    run_id=run_id,
                    payload={"confidence": confidence, "fallback": fallback},
                )
                self.state.add_episode(
                    cycle=cycle,
                    kind="task_idea_promoted",
                    content=f"task_id={task_id} -> creative",
                    score=confidence,
                )
                promoted += 1
            except Exception as exc:
                self.state.complete_task_run(
                    run_id=run_id,
                    status="failed",
                    stderr_log=str(exc),
                    metrics={"stage": "idea_to_creative", "failed": True},
                )
                self.state.add_agent_event(
                    cycle=cycle,
                    event_type="task_idea_promotion_failed",
                    severity="warning",
                    message=f"task_id={task_id} idea promotion failed: {exc}",
                    task_id=task_id,
                    run_id=run_id,
                )
        return promoted

    def _process_creative_tasks(self, cycle: int) -> int:
        promoted = 0
        creative_tasks = self.state.list_tasks(status="creative", limit=self.config.task_funnel_batch_size)
        for task in creative_tasks:
            task_id = int(task["id"])
            run_id = self.state.create_task_run(
                task_id=task_id,
                worker="acc.creative_planner",
                input_payload={
                    "task_id": task_id,
                    "task_key": task.get("task_key"),
                    "title": task["title"],
                    "description": task["description"],
                    "human_gate": self.config.task_human_feedback_gate,
                },
                status="running",
                metrics={"stage": "creative_to_queue"},
            )
            try:
                prompt = (
                    "Evaluate if this creative task is ready for execution queue.\n"
                    "Return strict JSON with keys: decision, task_title, task_description, confidence, rationale.\n"
                    "decision must be queue or stay_creative.\n"
                    f"title={task['title']}\n"
                    f"description={task['description']}"
                )
                raw = self.llm.generate(prompt)
                data = self._extract_json_object(raw)
                fallback = self._is_fallback_text(raw) or data is None

                decision = "stay_creative"
                confidence = 0.42
                rationale = "continue exploration"
                queued_title = str(task["title"]).strip()
                queued_description = str(task["description"]).strip()

                if data is not None:
                    if isinstance(data.get("decision"), str) and data["decision"].strip():
                        candidate = data["decision"].strip().lower()
                        if candidate in {"queue", "stay_creative"}:
                            decision = candidate
                    if isinstance(data.get("confidence"), (int, float)):
                        confidence = max(0.0, min(1.0, float(data["confidence"])))
                    if isinstance(data.get("rationale"), str) and data["rationale"].strip():
                        rationale = data["rationale"].strip()[:320]
                    if isinstance(data.get("task_title"), str) and data["task_title"].strip():
                        queued_title = data["task_title"].strip()[:180]
                    if isinstance(data.get("task_description"), str) and data["task_description"].strip():
                        queued_description = data["task_description"].strip()[:1200]
                elif self._heuristic_ready_for_queue(queued_description):
                    decision = "queue"
                    confidence = 0.58
                    rationale = "heuristic readiness from actionable description"

                if decision == "queue":
                    self.state.update_task_brief(
                        task_id=task_id,
                        title=queued_title,
                        description=queued_description,
                    )
                    if self.config.task_human_feedback_gate:
                        next_status = "blocked"
                        review_decision = "needs_human_feedback"
                        event_type = "task_human_feedback_required"
                        event_message = f"task_id={task_id} awaiting human approval for queue"
                    else:
                        next_status = "queued"
                        review_decision = "promote_queued"
                        event_type = "task_promoted_creative_to_queued"
                        event_message = f"task_id={task_id} promoted to queued"
                    promoted += 1

                    self.state.update_task_status(
                        task_id=task_id,
                        status=next_status,
                        result_summary=rationale,
                    )
                    self.state.add_episode(
                        cycle=cycle,
                        kind="task_creative_promoted",
                        content=f"task_id={task_id} -> {next_status}",
                        score=confidence,
                    )
                else:
                    review_decision = "stay_creative"
                    event_type = "task_kept_creative"
                    event_message = f"task_id={task_id} stays creative"
                    self.state.update_task_status(
                        task_id=task_id,
                        status="creative",
                        result_summary=rationale,
                    )

                self.state.complete_task_run(
                    run_id=run_id,
                    status="succeeded",
                    output_payload={
                        "decision": decision,
                        "next_status": self.state.get_task(task_id)["status"],
                        "task_title": queued_title,
                        "task_description": queued_description,
                        "confidence": confidence,
                        "fallback": fallback,
                    },
                    metrics={"fallback": fallback, "confidence": confidence, "decision": decision},
                )
                self.state.add_task_review(
                    task_id=task_id,
                    run_id=run_id,
                    reviewer="acc.creative_planner",
                    decision=review_decision,
                    score=confidence,
                    feedback=rationale,
                    meta={"cycle": cycle, "fallback": fallback},
                )
                self.state.add_agent_event(
                    cycle=cycle,
                    event_type=event_type,
                    severity="info",
                    message=event_message,
                    task_id=task_id,
                    run_id=run_id,
                    payload={"confidence": confidence, "fallback": fallback},
                )
            except Exception as exc:
                self.state.complete_task_run(
                    run_id=run_id,
                    status="failed",
                    stderr_log=str(exc),
                    metrics={"stage": "creative_to_queue", "failed": True},
                )
                self.state.add_agent_event(
                    cycle=cycle,
                    event_type="task_creative_promotion_failed",
                    severity="warning",
                    message=f"task_id={task_id} creative promotion failed: {exc}",
                    task_id=task_id,
                    run_id=run_id,
                )
        return promoted

    def process_task_funnel(self, cycle: int | None = None) -> int:
        effective_cycle = cycle if cycle is not None else max(1, self.state.next_cycle_number())
        promoted = 0
        promoted += self._process_idea_tasks(cycle=effective_cycle)
        promoted += self._process_creative_tasks(cycle=effective_cycle)
        return promoted

    def review_human_gate_task(
        self,
        task_ref: str,
        approved: bool,
        feedback: str = "",
        reviewer: str = "human",
    ) -> dict:
        task = self.state.resolve_task_reference(task_ref)
        if task is None:
            raise ValueError(f"Task not found: {task_ref}")

        task_id = int(task["id"])
        if str(task["status"]) != "blocked":
            raise ValueError(f"Task {task['task_key']} is not blocked (status={task['status']})")

        cycle = max(1, self.state.next_cycle_number())
        if approved:
            next_status = "queued"
            decision = "human_approved"
            message = "Task approved by human feedback gate"
            score = 1.0
        else:
            next_status = "creative"
            decision = "human_rework"
            message = "Task returned to creative stage by human feedback gate"
            score = 0.0

        self.state.update_task_status(task_id=task_id, status=next_status, result_summary=feedback or message)
        review_id = self.state.add_task_review(
            task_id=task_id,
            reviewer=reviewer,
            decision=decision,
            score=score,
            feedback=feedback or message,
            meta={"cycle": cycle, "manual": True},
        )
        event_id = self.state.add_agent_event(
            cycle=cycle,
            event_type="task_human_feedback_resolved",
            severity="info",
            message=f"task_id={task_id} decision={decision}",
            task_id=task_id,
            payload={"review_id": review_id, "decision": decision},
        )
        auto_actions = self._auto_handle_human_feedback(
            task_id=task_id,
            approved=approved,
            feedback=feedback,
            cycle=cycle,
        )
        updated = self.state.get_task(task_id)
        return {
            "task_id": task_id,
            "task_key": updated["task_key"] if updated else task.get("task_key"),
            "status": updated["status"] if updated else next_status,
            "decision": decision,
            "review_id": review_id,
            "event_id": event_id,
            "auto_actions": auto_actions,
        }

    def submit_external_request(
        self,
        user_text: str,
        session_id: str = "default",
        priority: float = 0.98,
    ) -> int:
        cycle_hint = max(1, self.state.next_cycle_number())
        goal_text = f"Handle user request: {user_text.strip()}"
        goal_id = self.state.create_goal(
            description=goal_text,
            source=f"external:user:{session_id}",
            priority=priority,
        )
        turn_id = self.state.add_dialog_turn(session_id=session_id, role="user", content=user_text)
        self.memory.add_entry(
            cycle=cycle_hint,
            source_kind="dialog_user",
            source_id=turn_id,
            text=user_text,
        )
        self.memory.add_entry(
            cycle=cycle_hint,
            source_kind="goal_external",
            source_id=goal_id,
            text=goal_text,
        )
        self.state.add_episode(
            cycle=cycle_hint,
            kind="external_goal_received",
            content=f"session={session_id} goal_id={goal_id}",
            score=priority,
        )
        return goal_id

    def generate_external_response(
        self,
        goal_id: int,
        user_text: str,
        session_id: str = "default",
    ) -> str:
        goal = self.state.get_goal(goal_id)
        hypotheses = self.state.list_hypotheses_for_goal(goal_id=goal_id, limit=6)
        history = self.state.get_dialog_history(session_id=session_id, limit=8)
        cycle_hint = max(1, self.state.next_cycle_number())

        if not hypotheses:
            response = (
                "Ich habe deine Anfrage aufgenommen, aber noch keine ausreichende interne "
                "Hypothese berechnet. Bitte gib mir mehr Zyklen fuer die Verarbeitung."
            )
        else:
            hyp_lines: list[str] = []
            for item in hypotheses:
                text = str(item["text"]).replace("\n", " ").strip()[:280]
                hyp_lines.append(
                    f"- decision={item['decision']} conf={float(item['confidence']):.2f} text={text}"
                )
            hist_lines: list[str] = []
            for item in history:
                content = str(item["content"]).replace("\n", " ").strip()[:180]
                hist_lines.append(f"- {item['role']}: {content}")

            response_prompt = (
                "Erstelle eine direkte, natuerliche Antwort auf die Nutzeranfrage in deutscher Sprache.\n"
                f"Nutzeranfrage: {user_text}\n"
                f"Goal status: {goal['status'] if goal else 'unknown'}\n"
                f"Interne Hypothesen:\n{chr(10).join(hyp_lines)}\n"
                f"Kontext (letzte Dialogturns):\n{chr(10).join(hist_lines) if hist_lines else '- none'}\n"
                "Gib eine klare Antwort mit kurzer Empfehlung und kurzem Confidence-Hinweis."
            )
            response = self.llm.generate(response_prompt)
            if response.startswith("Heuristic proposal:") or "Fallback:" in response:
                response = self._deterministic_external_response(
                    user_text=user_text,
                    hypotheses=hypotheses,
                    goal_status=goal["status"] if goal else None,
                )

        turn_id = self.state.add_dialog_turn(session_id=session_id, role="assistant", content=response)
        self.memory.add_entry(
            cycle=cycle_hint,
            source_kind="dialog_assistant",
            source_id=turn_id,
            text=response,
        )
        self.state.add_episode(
            cycle=cycle_hint,
            kind="external_response_generated",
            content=f"session={session_id} goal_id={goal_id}",
        )
        return response

    def run(self, cycles: int | None = None) -> RunSummary:
        target_cycles = cycles if cycles is not None else self.config.max_cycles
        started_at = self._now_iso()
        autonomous_tasks = 0
        start_cycle = self.state.next_cycle_number()
        end_cycle = start_cycle + target_cycles - 1

        self.state.bootstrap_self_model()

        for cycle in range(start_cycle, end_cycle + 1):
            if self.config.task_funnel_enabled:
                self.process_task_funnel(cycle=cycle)
            self.process_kidiekiruft_sync(cycle=cycle)
            if self.config.task_execution_enabled:
                autonomous_tasks += self.process_task_execution(cycle=cycle)
            snapshot = self.state.observe_internal_state(cycle)
            open_goals = self.state.list_open_goals(limit=20)

            new_goals = self.goal_generator.generate(
                snapshot=snapshot,
                open_goals=open_goals,
                uncertainty_threshold=self.policy.uncertainty_threshold,
                conflict_threshold=self.policy.conflict_threshold,
                novelty_threshold=self.policy.novelty_threshold,
            )
            for generated in new_goals:
                goal_id = self.state.create_goal(
                    generated.description,
                    generated.source,
                    generated.priority,
                )
                self.memory.add_entry(
                    cycle=cycle,
                    source_kind="goal",
                    source_id=goal_id,
                    text=generated.description,
                )
                autonomous_tasks += 1
                self.state.add_episode(
                    cycle,
                    "goal_generated",
                    f"goal_id={goal_id} source={generated.source} desc={generated.description}",
                    generated.priority,
                )

            active_goals = self.state.list_open_goals(limit=3)
            if not active_goals:
                self.state.add_episode(cycle, "idle", "no active goals and no intrinsic trigger")
                old_policy = self.policy
                self.policy = self.self_mod.process_cycle(cycle, snapshot)
                if self.policy != old_policy:
                    self.state.add_episode(
                        cycle,
                        "policy_updated",
                        (
                            f"u_thr={self.policy.uncertainty_threshold:.3f} "
                            f"c_thr={self.policy.conflict_threshold:.3f} "
                            f"n_thr={self.policy.novelty_threshold:.3f} "
                            f"explore={self.policy.exploration_factor:.3f} "
                            f"mem_k={self.policy.memory_retrieval_k} "
                            f"mem_min={self.policy.memory_min_score:.3f}"
                        ),
                    )
                if self.config.tick_interval_sec > 0:
                    time.sleep(self.config.tick_interval_sec)
                continue

            self_model = self.state.get_self_model()

            for goal in active_goals:
                memory_query = (
                    f"{goal['description']} "
                    f"uncertainty={snapshot.uncertainty:.2f} conflict={snapshot.conflict:.2f}"
                )
                memories = self.memory.retrieve(
                    query=memory_query,
                    top_k=self.policy.memory_retrieval_k,
                    min_score=self.policy.memory_min_score,
                )
                if memories:
                    detail = ",".join(f"{m.id}:{m.score:.2f}" for m in memories)
                    self.state.add_episode(
                        cycle=cycle,
                        kind="memory_retrieved",
                        content=f"goal_id={goal['id']} memories={detail}",
                    )

                prompt = self._build_prompt(goal, snapshot, self_model, memories)
                hypothesis = self.llm.generate(prompt)

                evaluation = self.meta.evaluate(snapshot, float(goal["priority"]))
                weaknesses = ",".join(evaluation.weaknesses)
                hypothesis_id = self.state.add_hypothesis(
                    cycle=cycle,
                    goal_id=int(goal["id"]),
                    text=hypothesis,
                    confidence=evaluation.confidence,
                    weaknesses=weaknesses,
                    decision=evaluation.decision,
                )
                self.memory.add_entry(
                    cycle=cycle,
                    source_kind="hypothesis",
                    source_id=hypothesis_id,
                    text=hypothesis,
                )
                self.state.add_episode(
                    cycle,
                    "hypothesis_evaluated",
                    f"goal_id={goal['id']} decision={evaluation.decision} confidence={evaluation.confidence:.2f}",
                    evaluation.confidence,
                )

                if evaluation.decision == "commit":
                    self.state.upsert_self_model("strategy", "iterative_uncertainty_reduction_with_conflict_checks")
                    if evaluation.confidence >= 0.67:
                        self.state.resolve_goal(int(goal["id"]))
                        self.state.add_episode(
                            cycle,
                            "goal_resolved",
                            f"goal_id={goal['id']} confidence={evaluation.confidence:.2f}",
                            evaluation.confidence,
                        )

                if self.exploration.should_branch(
                    evaluation.decision,
                    evaluation.confidence,
                    self.policy.exploration_factor,
                ):
                    branch = self.exploration.branch_hypothesis(hypothesis)
                    branch_conf = max(0.0, evaluation.confidence - 0.08)
                    branch_id = self.state.add_hypothesis(
                        cycle=cycle,
                        goal_id=int(goal["id"]),
                        text=branch,
                        confidence=branch_conf,
                        weaknesses="counterfactual_branch",
                        decision="branch",
                    )
                    self.memory.add_entry(
                        cycle=cycle,
                        source_kind="hypothesis_branch",
                        source_id=branch_id,
                        text=branch,
                    )
                    self.state.add_episode(
                        cycle,
                        "branch_created",
                        f"goal_id={goal['id']} branch_confidence={branch_conf:.2f}",
                        branch_conf,
                    )

            old_policy = self.policy
            self.policy = self.self_mod.process_cycle(cycle, snapshot)
            if self.policy != old_policy:
                self.state.add_episode(
                    cycle,
                    "policy_updated",
                    (
                        f"u_thr={self.policy.uncertainty_threshold:.3f} "
                        f"c_thr={self.policy.conflict_threshold:.3f} "
                        f"n_thr={self.policy.novelty_threshold:.3f} "
                        f"explore={self.policy.exploration_factor:.3f} "
                        f"mem_k={self.policy.memory_retrieval_k} "
                        f"mem_min={self.policy.memory_min_score:.3f}"
                    ),
                )

            if self.config.tick_interval_sec > 0:
                time.sleep(self.config.tick_interval_sec)

        avg_uncertainty = self.state.avg_uncertainty_for_latest_cycles(target_cycles)
        ended_at = self._now_iso()
        self.state.record_run(
            started_at=started_at,
            ended_at=ended_at,
            cycles=target_cycles,
            autonomous_tasks=autonomous_tasks,
            avg_uncertainty=avg_uncertainty,
        )

        return RunSummary(
            cycles=target_cycles,
            start_cycle=start_cycle,
            end_cycle=end_cycle,
            autonomous_tasks=autonomous_tasks,
            avg_uncertainty=avg_uncertainty,
            db_path=self.config.db_path,
        )

    def close(self) -> None:
        self.db.close()
