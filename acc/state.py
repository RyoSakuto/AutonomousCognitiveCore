from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import ACCDatabase


@dataclass
class StateSnapshot:
    cycle: int
    uncertainty: float
    conflict: float
    novelty: float
    tension: float
    open_goals: int


class StateStore:
    def __init__(self, db: ACCDatabase, seed: int = 7) -> None:
        self.db = db
        self._rng = random.Random(seed)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _as_json_text(value: str | dict | list | None) -> str:
        if value is None:
            return "{}"
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    def next_cycle_number(self) -> int:
        row = self.db.conn.execute("SELECT COALESCE(MAX(cycle), 0) AS c FROM metrics").fetchone()
        return int(row["c"]) + 1

    def bootstrap_self_model(self) -> None:
        defaults = {
            "identity": "Autonomous Cognitive Core Prototype",
            "capabilities": "state_tracking, goal_generation, self_evaluation, exploration",
            "limitations": "heuristic_reasoning_only",
            "strategy": "reduce_uncertainty_and_conflict",
        }
        for key, value in defaults.items():
            self.upsert_self_model(key, value)

    def upsert_self_model(self, key: str, value: str) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            INSERT INTO self_model(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now),
        )
        self.db.conn.commit()

    def get_self_model(self) -> dict[str, str]:
        rows = self.db.conn.execute("SELECT key, value FROM self_model").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def get_open_goal_count(self) -> int:
        return int(
            self.db.conn.execute("SELECT COUNT(*) AS c FROM goals WHERE status='open'").fetchone()["c"]
        )

    def observe_internal_state(self, cycle: int) -> StateSnapshot:
        open_goals = self.get_open_goal_count()
        recent_commits = self.db.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM (
                SELECT decision FROM hypotheses ORDER BY id DESC LIMIT 6
            )
            WHERE decision='commit'
            """
        ).fetchone()["c"]
        recent_resolutions = self.db.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM goals
            WHERE status='resolved'
              AND id IN (
                  SELECT id FROM goals WHERE status='resolved' ORDER BY id DESC LIMIT 10
              )
            """
        ).fetchone()["c"]
        recent_resolutions = min(int(recent_resolutions), 2)

        last = self.db.conn.execute(
            "SELECT uncertainty, conflict, novelty FROM metrics ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if last:
            u_base = float(last["uncertainty"]) * 0.88 + 0.10
            c_base = float(last["conflict"]) * 0.85 + 0.08
            n_base = float(last["novelty"]) * 0.70 + 0.20
        else:
            u_base, c_base, n_base = 0.52, 0.35, 0.62

        uncertainty = self._clamp01(
            u_base
            + open_goals * 0.022
            - recent_commits * 0.03
            - recent_resolutions * 0.04
            + self._rng.uniform(-0.05, 0.05)
        )
        conflict = self._clamp01(
            c_base
            + open_goals * 0.018
            - recent_commits * 0.02
            - recent_resolutions * 0.025
            + self._rng.uniform(-0.05, 0.05)
        )
        uncertainty = max(0.08, uncertainty)
        conflict = max(0.06, conflict)
        novelty = self._clamp01(n_base - recent_resolutions * 0.02 + self._rng.uniform(-0.08, 0.07))
        tension = self._clamp01(0.45 * uncertainty + 0.35 * conflict + 0.20 * novelty)

        now = self._now_iso()
        self.db.conn.execute(
            """
            INSERT INTO metrics(cycle, uncertainty, conflict, novelty, tension, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (cycle, uncertainty, conflict, novelty, tension, now),
        )
        self.db.conn.commit()

        return StateSnapshot(
            cycle=cycle,
            uncertainty=uncertainty,
            conflict=conflict,
            novelty=novelty,
            tension=tension,
            open_goals=open_goals,
        )

    def create_goal(self, description: str, source: str, priority: float) -> int:
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO goals(description, source, status, priority, created_at)
            VALUES(?, ?, 'open', ?, ?)
            """,
            (description, source, priority, now),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def list_open_goals(self, limit: int = 5) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT id, description, source, priority, created_at
            FROM goals
            WHERE status='open'
            ORDER BY priority DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def resolve_goal(self, goal_id: int) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            "UPDATE goals SET status='resolved', resolved_at=? WHERE id=?",
            (now, goal_id),
        )
        self.db.conn.commit()

    def add_episode(self, cycle: int, kind: str, content: str, score: float | None = None) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            INSERT INTO episodes(cycle, kind, content, score, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (cycle, kind, content, score, now),
        )
        self.db.conn.commit()

    def add_hypothesis(
        self,
        cycle: int,
        goal_id: int | None,
        text: str,
        confidence: float,
        weaknesses: str,
        decision: str,
    ) -> int:
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO hypotheses(cycle, goal_id, text, confidence, weaknesses, decision, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (cycle, goal_id, text, confidence, weaknesses, decision, now),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def get_goal(self, goal_id: int) -> dict | None:
        row = self.db.conn.execute(
            """
            SELECT id, description, source, status, priority, created_at, resolved_at
            FROM goals
            WHERE id=?
            """,
            (goal_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_hypotheses_for_goal(self, goal_id: int, limit: int = 8) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT id, cycle, text, confidence, weaknesses, decision, created_at
            FROM hypotheses
            WHERE goal_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (goal_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_dialog_turn(self, session_id: str, role: str, content: str) -> int:
        now = self._now_iso()
        row = self.db.conn.execute(
            "SELECT COALESCE(MAX(turn_index), 0) AS t FROM dialog_turns WHERE session_id=?",
            (session_id,),
        ).fetchone()
        next_turn = int(row["t"]) + 1
        cur = self.db.conn.execute(
            """
            INSERT INTO dialog_turns(session_id, turn_index, role, content, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (session_id, next_turn, role, content, now),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def get_dialog_history(self, session_id: str, limit: int = 12) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT id, session_id, turn_index, role, content, created_at
            FROM dialog_turns
            WHERE session_id=?
            ORDER BY turn_index DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def create_task(
        self,
        title: str,
        description: str,
        source: str,
        priority: float = 0.5,
        status: str = "queued",
        owner: str | None = None,
        parent_task_id: int | None = None,
        due_at: str | None = None,
        context: str | dict | list | None = None,
        task_key: str | None = None,
    ) -> int:
        normalized_status = status.strip().lower()
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO tasks(
                task_key, parent_task_id, title, description, source, status, priority,
                owner, context_json, due_at, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_key,
                parent_task_id,
                title,
                description,
                source,
                normalized_status,
                priority,
                owner,
                self._as_json_text(context),
                due_at,
                now,
                now,
            ),
        )
        task_id = int(cur.lastrowid)
        if task_key is None:
            generated_key = f"TASK-{task_id:05d}"
            self.db.conn.execute(
                "UPDATE tasks SET task_key=?, updated_at=? WHERE id=?",
                (generated_key, now, task_id),
            )
        self.db.conn.commit()
        return task_id

    def get_task(self, task_id: int) -> dict | None:
        row = self.db.conn.execute(
            """
            SELECT
                id, task_key, parent_task_id, title, description, source, status, priority,
                owner, context_json, result_summary, error_text, started_at, finished_at,
                due_at, created_at, updated_at
            FROM tasks
            WHERE id=?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_task_by_key(self, task_key: str) -> dict | None:
        row = self.db.conn.execute(
            """
            SELECT
                id, task_key, parent_task_id, title, description, source, status, priority,
                owner, context_json, result_summary, error_text, started_at, finished_at,
                due_at, created_at, updated_at
            FROM tasks
            WHERE task_key=?
            """,
            (task_key,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def resolve_task_reference(self, task_ref: str) -> dict | None:
        ref = task_ref.strip()
        if ref.isdigit():
            return self.get_task(int(ref))
        return self.get_task_by_key(ref)

    def add_task_dependency(
        self,
        task_id: int,
        depends_on_task_id: int,
        dependency_type: str = "hard",
    ) -> int:
        if task_id == depends_on_task_id:
            raise ValueError("task_id and depends_on_task_id must be different")

        now = self._now_iso()
        dep_type = dependency_type.strip().lower() if dependency_type else "hard"
        if dep_type not in {"hard", "soft"}:
            dep_type = "hard"

        cur = self.db.conn.execute(
            """
            INSERT OR IGNORE INTO task_dependencies(task_id, depends_on_task_id, dependency_type, created_at)
            VALUES(?, ?, ?, ?)
            """,
            (task_id, depends_on_task_id, dep_type, now),
        )
        if cur.rowcount == 0:
            row = self.db.conn.execute(
                """
                SELECT id
                FROM task_dependencies
                WHERE task_id=? AND depends_on_task_id=?
                """,
                (task_id, depends_on_task_id),
            ).fetchone()
            self.db.conn.commit()
            return int(row["id"]) if row is not None else 0
        dep_id = int(cur.lastrowid)
        self.db.conn.commit()
        return dep_id

    def list_task_dependencies(self, task_id: int, include_status: bool = False) -> list[dict]:
        if not include_status:
            rows = self.db.conn.execute(
                """
                SELECT id, task_id, depends_on_task_id, dependency_type, created_at
                FROM task_dependencies
                WHERE task_id=?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
            return [dict(row) for row in rows]

        rows = self.db.conn.execute(
            """
            SELECT
                td.id,
                td.task_id,
                td.depends_on_task_id,
                td.dependency_type,
                td.created_at,
                t.task_key AS depends_on_task_key,
                t.title AS depends_on_title,
                t.status AS depends_on_status
            FROM task_dependencies td
            LEFT JOIN tasks t ON t.id=td.depends_on_task_id
            WHERE td.task_id=?
            ORDER BY td.id ASC
            """,
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_unmet_task_dependencies(self, task_id: int) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT
                td.id,
                td.task_id,
                td.depends_on_task_id,
                td.dependency_type,
                t.task_key AS depends_on_task_key,
                t.title AS depends_on_title,
                t.status AS depends_on_status
            FROM task_dependencies td
            LEFT JOIN tasks t ON t.id=td.depends_on_task_id
            WHERE td.task_id=?
              AND (
                t.id IS NULL
                OR (LOWER(td.dependency_type)='hard' AND LOWER(COALESCE(t.status, 'unknown'))!='done')
                OR (
                    LOWER(td.dependency_type)='soft'
                    AND LOWER(COALESCE(t.status, 'unknown')) IN ('failed', 'cancelled', 'canceled')
                )
              )
            ORDER BY td.id ASC
            """,
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_task_brief(self, task_id: int, title: str, description: str) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            UPDATE tasks
            SET title=?, description=?, updated_at=?
            WHERE id=?
            """,
            (title, description, now, task_id),
        )
        self.db.conn.commit()

    def update_task_context(self, task_id: int, context: dict, merge: bool = True) -> None:
        now = self._now_iso()
        payload = context if isinstance(context, dict) else {}
        if merge:
            current = self.get_task(task_id)
            merged: dict = {}
            if current is not None and isinstance(current.get("context_json"), str):
                try:
                    existing = json.loads(str(current["context_json"]))
                    if isinstance(existing, dict):
                        merged.update(existing)
                except json.JSONDecodeError:
                    pass
            merged.update(payload)
            payload = merged
        self.db.conn.execute(
            """
            UPDATE tasks
            SET context_json=?, updated_at=?
            WHERE id=?
            """,
            (self._as_json_text(payload), now, task_id),
        )
        self.db.conn.commit()

    def list_tasks(self, status: str | None = None, limit: int = 20) -> list[dict]:
        if status is None:
            rows = self.db.conn.execute(
                """
                SELECT
                    id, task_key, parent_task_id, title, description, source, status, priority,
                    owner, context_json, result_summary, error_text, started_at, finished_at,
                    due_at, created_at, updated_at
                FROM tasks
                ORDER BY
                    CASE status
                        WHEN 'idea' THEN 0
                        WHEN 'creative' THEN 1
                        WHEN 'queued' THEN 2
                        WHEN 'running' THEN 3
                        WHEN 'rework' THEN 4
                        WHEN 'blocked' THEN 5
                        WHEN 'done' THEN 6
                        WHEN 'failed' THEN 7
                        WHEN 'cancelled' THEN 8
                        WHEN 'canceled' THEN 8
                        ELSE 99
                    END,
                    priority DESC,
                    id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """
                SELECT
                    id, task_key, parent_task_id, title, description, source, status, priority,
                    owner, context_json, result_summary, error_text, started_at, finished_at,
                    due_at, created_at, updated_at
                FROM tasks
                WHERE status=?
                ORDER BY priority DESC, id ASC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_next_task(self, worker: str) -> dict | None:
        now = self._now_iso()
        conn = self.db.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """
                SELECT id
                FROM tasks
                WHERE status='queued'
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None

            task_id = int(row["id"])
            conn.execute(
                """
                UPDATE tasks
                SET status='running',
                    owner=?,
                    started_at=COALESCE(started_at, ?),
                    updated_at=?
                WHERE id=?
                """,
                (worker, now, now, task_id),
            )
            conn.commit()
            return self.get_task(task_id)
        except sqlite3.Error:
            conn.rollback()
            raise

    def claim_task(self, task_id: int, worker: str) -> dict | None:
        now = self._now_iso()
        conn = self.db.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                """
                UPDATE tasks
                SET status='running',
                    owner=?,
                    started_at=COALESCE(started_at, ?),
                    updated_at=?
                WHERE id=? AND status='queued'
                """,
                (worker, now, now, task_id),
            )
            if cur.rowcount == 0:
                conn.commit()
                return None
            conn.commit()
            return self.get_task(task_id)
        except sqlite3.Error:
            conn.rollback()
            raise

    def update_task_status(
        self,
        task_id: int,
        status: str,
        result_summary: str | None = None,
        error_text: str | None = None,
    ) -> None:
        normalized_status = status.strip().lower()
        now = self._now_iso()
        terminal_status = {"done", "failed", "cancelled", "canceled"}
        if normalized_status == "running":
            self.db.conn.execute(
                """
                UPDATE tasks
                SET status=?, started_at=COALESCE(started_at, ?), updated_at=?
                WHERE id=?
                """,
                (normalized_status, now, now, task_id),
            )
        elif normalized_status in terminal_status:
            self.db.conn.execute(
                """
                UPDATE tasks
                SET status=?,
                    result_summary=COALESCE(?, result_summary),
                    error_text=COALESCE(?, error_text),
                    finished_at=?,
                    updated_at=?
                WHERE id=?
                """,
                (normalized_status, result_summary, error_text, now, now, task_id),
            )
        else:
            self.db.conn.execute(
                """
                UPDATE tasks
                SET status=?,
                    result_summary=COALESCE(?, result_summary),
                    error_text=COALESCE(?, error_text),
                    updated_at=?
                WHERE id=?
                """,
                (normalized_status, result_summary, error_text, now, task_id),
            )
        self.db.conn.commit()

    def create_task_run(
        self,
        task_id: int,
        worker: str,
        input_payload: str | dict | list | None = None,
        status: str = "started",
        metrics: str | dict | list | None = None,
    ) -> int:
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO task_runs(
                task_id, worker, status, input_payload, metrics_json, started_at, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                worker,
                status,
                self._as_json_text(input_payload),
                self._as_json_text(metrics),
                now,
                now,
                now,
            ),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def complete_task_run(
        self,
        run_id: int,
        status: str,
        output_payload: str | dict | list | None = None,
        stdout_log: str | None = None,
        stderr_log: str | None = None,
        metrics: str | dict | list | None = None,
        duration_ms: int | None = None,
    ) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            UPDATE task_runs
            SET status=?,
                output_payload=COALESCE(?, output_payload),
                stdout_log=COALESCE(?, stdout_log),
                stderr_log=COALESCE(?, stderr_log),
                metrics_json=COALESCE(?, metrics_json),
                ended_at=?,
                duration_ms=COALESCE(?, duration_ms),
                updated_at=?
            WHERE id=?
            """,
            (
                status,
                None if output_payload is None else self._as_json_text(output_payload),
                stdout_log,
                stderr_log,
                None if metrics is None else self._as_json_text(metrics),
                now,
                duration_ms,
                now,
                run_id,
            ),
        )
        self.db.conn.commit()

    def list_task_runs(self, task_id: int, limit: int = 12) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT
                id, task_id, worker, status, input_payload, output_payload, stdout_log, stderr_log,
                metrics_json, started_at, ended_at, duration_ms, created_at, updated_at
            FROM task_runs
            WHERE task_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (task_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_task_runs(self, task_id: int, status: str | None = None) -> int:
        if status is None:
            row = self.db.conn.execute(
                "SELECT COUNT(*) AS c FROM task_runs WHERE task_id=?",
                (task_id,),
            ).fetchone()
        else:
            row = self.db.conn.execute(
                "SELECT COUNT(*) AS c FROM task_runs WHERE task_id=? AND status=?",
                (task_id, status),
            ).fetchone()
        return int(row["c"]) if row is not None else 0

    def get_recent_task_runs(self, limit: int = 120) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT
                id, task_id, worker, status, output_payload, metrics_json, started_at, ended_at, duration_ms
            FROM task_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_task_review(
        self,
        task_id: int,
        reviewer: str,
        decision: str,
        feedback: str,
        score: float | None = None,
        run_id: int | None = None,
        meta: str | dict | list | None = None,
    ) -> int:
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO task_reviews(
                task_id, run_id, reviewer, decision, score, feedback, meta_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                run_id,
                reviewer,
                decision,
                score,
                feedback,
                self._as_json_text(meta),
                now,
            ),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def list_task_reviews(self, task_id: int, limit: int = 12) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT id, task_id, run_id, reviewer, decision, score, feedback, meta_json, created_at
            FROM task_reviews
            WHERE task_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (task_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_agent_event(
        self,
        event_type: str,
        message: str,
        severity: str = "info",
        cycle: int | None = None,
        task_id: int | None = None,
        run_id: int | None = None,
        payload: str | dict | list | None = None,
    ) -> int:
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO agent_events(
                cycle, event_type, severity, message, task_id, run_id, payload_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle,
                event_type,
                severity,
                message,
                task_id,
                run_id,
                self._as_json_text(payload),
                now,
            ),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def list_agent_events(
        self,
        limit: int = 40,
        event_type: str | None = None,
        severity: str | None = None,
        task_id: int | None = None,
    ) -> list[dict]:
        query = """
            SELECT id, cycle, event_type, severity, message, task_id, run_id, payload_json, created_at
            FROM agent_events
        """
        clauses: list[str] = []
        params: list[object] = []
        if event_type is not None:
            clauses.append("event_type=?")
            params.append(event_type)
        if severity is not None:
            clauses.append("severity=?")
            params.append(severity)
        if task_id is not None:
            clauses.append("task_id=?")
            params.append(task_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.db.conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def bootstrap_runtime_params(self, defaults: dict[str, float]) -> None:
        now = self._now_iso()
        for key, value in defaults.items():
            self.db.conn.execute(
                """
                INSERT OR IGNORE INTO runtime_params(key, value, updated_at)
                VALUES(?, ?, ?)
                """,
                (key, str(value), now),
            )
        self.db.conn.commit()

    def get_runtime_params(self) -> dict[str, float]:
        rows = self.db.conn.execute("SELECT key, value FROM runtime_params").fetchall()
        out: dict[str, float] = {}
        for row in rows:
            try:
                out[str(row["key"])] = float(row["value"])
            except (TypeError, ValueError):
                continue
        return out

    def upsert_runtime_param(self, key: str, value: float) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            INSERT INTO runtime_params(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, str(value), now),
        )
        self.db.conn.commit()

    def create_self_mod_proposal(
        self,
        cycle: int,
        parameter: str,
        old_value: float,
        new_value: float,
        rationale: str,
        expected_effect: str,
        risk_level: float,
        simulation_score: float,
        status: str,
        note: str | None = None,
    ) -> int:
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO self_mod_proposals(
                cycle, parameter, old_value, new_value, rationale,
                expected_effect, risk_level, simulation_score, status,
                note, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle,
                parameter,
                old_value,
                new_value,
                rationale,
                expected_effect,
                risk_level,
                simulation_score,
                status,
                note,
                now,
                now,
            ),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def update_self_mod_proposal_status(self, proposal_id: int, status: str, note: str | None = None) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            UPDATE self_mod_proposals
            SET status=?, note=?, updated_at=?
            WHERE id=?
            """,
            (status, note, now, proposal_id),
        )
        self.db.conn.commit()

    def add_self_mod_audit(
        self,
        cycle: int,
        action: str,
        detail: str,
        proposal_id: int | None = None,
    ) -> None:
        now = self._now_iso()
        self.db.conn.execute(
            """
            INSERT INTO self_mod_audit(cycle, proposal_id, action, detail, created_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (cycle, proposal_id, action, detail, now),
        )
        self.db.conn.commit()

    def get_latest_approved_self_mod_cycle(self) -> int | None:
        row = self.db.conn.execute(
            """
            SELECT cycle
            FROM self_mod_proposals
            WHERE status='approved'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return int(row["cycle"])

    def get_self_mod_parameter_stats(self, window: int = 60) -> dict[str, dict]:
        rows = self.db.conn.execute(
            """
            SELECT
                parameter,
                SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved_count,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected_count,
                SUM(CASE WHEN status='rolled_back' THEN 1 ELSE 0 END) AS rolled_back_count,
                AVG(simulation_score) AS avg_simulation_score
            FROM (
                SELECT parameter, status, simulation_score
                FROM self_mod_proposals
                ORDER BY id DESC
                LIMIT ?
            )
            GROUP BY parameter
            """,
            (window,),
        ).fetchall()
        out: dict[str, dict] = {}
        for row in rows:
            key = str(row["parameter"])
            out[key] = {
                "approved_count": int(row["approved_count"] or 0),
                "rejected_count": int(row["rejected_count"] or 0),
                "rolled_back_count": int(row["rolled_back_count"] or 0),
                "avg_simulation_score": float(row["avg_simulation_score"] or 0.0),
            }
        return out

    def count_self_mod_proposals(
        self,
        status: str | None = None,
        cycle_from: int | None = None,
        cycle_to: int | None = None,
        parameter: str | None = None,
    ) -> int:
        query = "SELECT COUNT(*) AS c FROM self_mod_proposals"
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if cycle_from is not None:
            clauses.append("cycle>=?")
            params.append(cycle_from)
        if cycle_to is not None:
            clauses.append("cycle<=?")
            params.append(cycle_to)
        if parameter is not None:
            clauses.append("parameter=?")
            params.append(parameter)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        row = self.db.conn.execute(query, tuple(params)).fetchone()
        return int(row["c"]) if row is not None else 0

    def get_self_mod_status_counts_in_cycle_window(self, cycle: int, window: int) -> dict[str, int]:
        start_cycle = max(1, int(cycle) - max(1, int(window)) + 1)
        rows = self.db.conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM self_mod_proposals
            WHERE cycle>=? AND cycle<=?
            GROUP BY status
            """,
            (start_cycle, int(cycle)),
        ).fetchall()
        out: dict[str, int] = {}
        for row in rows:
            out[str(row["status"])] = int(row["c"])
        return out

    def get_recent_metrics(self, limit: int) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT cycle, uncertainty, conflict, novelty, tension
            FROM metrics
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_recent_decision_counts(self, limit: int) -> dict[str, int]:
        rows = self.db.conn.execute(
            """
            SELECT decision, COUNT(*) AS c
            FROM (
                SELECT decision FROM hypotheses ORDER BY id DESC LIMIT ?
            )
            GROUP BY decision
            """,
            (limit,),
        ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row["decision"])] = int(row["c"])
        return counts

    def count_recent_idle_cycles(self, limit: int) -> int:
        row = self.db.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM (
                SELECT kind FROM episodes ORDER BY id DESC LIMIT ?
            )
            WHERE kind='idle'
            """,
            (limit,),
        ).fetchone()
        return int(row["c"])

    def record_run(
        self,
        started_at: str,
        ended_at: str,
        cycles: int,
        autonomous_tasks: int,
        avg_uncertainty: float,
    ) -> None:
        self.db.conn.execute(
            """
            INSERT INTO runs(started_at, ended_at, cycles, autonomous_tasks, avg_uncertainty)
            VALUES(?, ?, ?, ?, ?)
            """,
            (started_at, ended_at, cycles, autonomous_tasks, avg_uncertainty),
        )
        self.db.conn.commit()

    def avg_uncertainty_for_latest_cycles(self, cycles: int) -> float:
        row = self.db.conn.execute(
            """
            SELECT AVG(uncertainty) AS avg_u
            FROM (
                SELECT uncertainty FROM metrics ORDER BY id DESC LIMIT ?
            )
            """,
            (cycles,),
        ).fetchone()
        return float(row["avg_u"] or 0.0)
