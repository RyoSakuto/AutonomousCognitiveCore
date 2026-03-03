import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nimcf.db"

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        text TEXT,
        valenz REAL,
        arousal REAL,
        importance REAL,
        source TEXT,
        last_access TEXT
    );
    CREATE TABLE IF NOT EXISTS ep_links (
        ep_id INTEGER,
        rel TEXT,
        target_id TEXT,
        target_type TEXT
    );
    CREATE TABLE IF NOT EXISTS trust (
        source TEXT PRIMARY KEY,
        score REAL
    );
    CREATE TABLE IF NOT EXISTS module_coactivations (
        src TEXT,
        dst TEXT,
        weight REAL,
        PRIMARY KEY (src, dst)
    );
    """)
    conn.commit()
    conn.close()

def connect():
    return sqlite3.connect(DB_PATH)

def add_episode(text, valenz=0.0, arousal=0.0, importance=5.0, source="user"):
    ts = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO trust (source, score) VALUES (?, ?)",
            (source, 0.5),
        )
        cur.execute("""
            INSERT INTO episodes (ts, text, valenz, arousal, importance, source, last_access)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ts, text, valenz, arousal, importance, source, ts))
        conn.commit()
        return cur.lastrowid

def get_episodes(limit=50):
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, ts, text, valenz, arousal, importance FROM episodes ORDER BY id DESC LIMIT ?", (limit,))
        return cur.fetchall()


def get_trust_scores() -> Dict[str, float]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT source, score FROM trust")
        return {row[0]: row[1] for row in cur.fetchall()}


def update_trust(source: str, delta: float | None = None, value: float | None = None) -> float:
    if delta is None and value is None:
        raise ValueError("Either delta or value must be provided for trust update.")
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO trust (source, score) VALUES (?, ?)",
            (source, 0.5),
        )
        if value is not None:
            score = max(0.0, min(1.0, value))
        else:
            cur.execute("SELECT score FROM trust WHERE source = ?", (source,))
            row = cur.fetchone()
            current = row[0] if row else 0.5
            score = max(0.0, min(1.0, current + delta))
        cur.execute("UPDATE trust SET score = ? WHERE source = ?", (score, source))
        conn.commit()
        return score


def bump_module_link(src: str, dst: str, delta: float = 1.0) -> None:
    if not src or not dst or src == dst:
        return
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO module_coactivations (src, dst, weight)
            VALUES (?, ?, ?)
            ON CONFLICT(src, dst) DO UPDATE SET weight = weight + excluded.weight
            """,
            (src, dst, delta),
        )
        conn.commit()


def load_module_coactivations() -> Dict[str, Dict[str, float]]:
    data: Dict[str, Dict[str, float]] = {}
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT src, dst, weight FROM module_coactivations")
        for src, dst, weight in cur.fetchall():
            data.setdefault(src, {})[dst] = weight
    return data
