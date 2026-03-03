from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS self_model (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  description TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  priority REAL NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  uncertainty REAL NOT NULL,
  conflict REAL NOT NULL,
  novelty REAL NOT NULL,
  tension REAL NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  score REAL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  goal_id INTEGER,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  weaknesses TEXT NOT NULL,
  decision TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  source_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_cycle ON memory_embeddings(cycle);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_source ON memory_embeddings(source_kind, source_id);

CREATE TABLE IF NOT EXISTS runtime_params (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS self_mod_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  parameter TEXT NOT NULL,
  old_value REAL NOT NULL,
  new_value REAL NOT NULL,
  rationale TEXT NOT NULL,
  expected_effect TEXT NOT NULL,
  risk_level REAL NOT NULL,
  simulation_score REAL NOT NULL,
  status TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_self_mod_proposals_cycle ON self_mod_proposals(cycle);
CREATE INDEX IF NOT EXISTS idx_self_mod_proposals_status ON self_mod_proposals(status);

CREATE TABLE IF NOT EXISTS self_mod_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  proposal_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(proposal_id) REFERENCES self_mod_proposals(id)
);

CREATE INDEX IF NOT EXISTS idx_self_mod_audit_cycle ON self_mod_audit(cycle);

CREATE TABLE IF NOT EXISTS dialog_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  turn_index INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dialog_turns_session ON dialog_turns(session_id, turn_index);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_key TEXT UNIQUE,
  parent_task_id INTEGER,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  priority REAL NOT NULL,
  owner TEXT,
  context_json TEXT NOT NULL,
  result_summary TEXT,
  error_text TEXT,
  started_at TEXT,
  finished_at TEXT,
  due_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(parent_task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority DESC, id ASC);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source);

CREATE TABLE IF NOT EXISTS task_dependencies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  depends_on_task_id INTEGER NOT NULL,
  dependency_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(task_id, depends_on_task_id),
  FOREIGN KEY(task_id) REFERENCES tasks(id),
  FOREIGN KEY(depends_on_task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_task_dependencies_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_dependencies_depends ON task_dependencies(depends_on_task_id);

CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  worker TEXT NOT NULL,
  status TEXT NOT NULL,
  input_payload TEXT NOT NULL,
  output_payload TEXT,
  stdout_log TEXT,
  stderr_log TEXT,
  metrics_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  duration_ms INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status);

CREATE TABLE IF NOT EXISTS task_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  run_id INTEGER,
  reviewer TEXT NOT NULL,
  decision TEXT NOT NULL,
  score REAL,
  feedback TEXT NOT NULL,
  meta_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id),
  FOREIGN KEY(run_id) REFERENCES task_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_task_reviews_task ON task_reviews(task_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_task_reviews_decision ON task_reviews(decision);

CREATE TABLE IF NOT EXISTS agent_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  task_id INTEGER,
  run_id INTEGER,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id),
  FOREIGN KEY(run_id) REFERENCES task_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events(event_type, id DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_task ON agent_events(task_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_cycle ON agent_events(cycle, id DESC);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  cycles INTEGER NOT NULL,
  autonomous_tasks INTEGER NOT NULL,
  avg_uncertainty REAL NOT NULL
);
"""


class ACCDatabase:
    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
