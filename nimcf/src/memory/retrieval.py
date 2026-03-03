from datetime import datetime, timezone
from typing import Dict, Optional

from .db import connect

def days_since(ts_str):
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta.days + delta.seconds / 86400.0

def score_episode(ep, query, weights=None, trust_score: float = 0.5):
    """Simple lexical + temporal + affective scoring."""
    weights = weights or dict(alpha=0.45, beta=0.2, gamma=0.2, delta=0.1, epsilon=0.05)
    text = ep[2].lower()
    recency = 1 / (1 + days_since(ep[1]))
    match_score = sum(1 for w in query.lower().split() if w in text) / max(len(query.split()), 1)
    importance = ep[5] / 10.0
    affect_bias = 0.5 * ep[3] + 0.5 * ep[4]
    return (
        weights["alpha"] * match_score +
        weights["beta"] * recency +
        weights["gamma"] * importance +
        weights["delta"] * affect_bias +
        weights["epsilon"] * trust_score
    )

def retrieve_relevant(query, k=5, weights: Optional[Dict[str, float]] = None):
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, ts, text, valenz, arousal, importance, source, last_access FROM episodes")
        rows = cur.fetchall()
        cur.execute("SELECT source, score FROM trust")
        trust_rows = {row[0]: row[1] for row in cur.fetchall()}

    scored = []
    for r in rows:
        trust_score = trust_rows.get(r[6], 0.5)
        scored.append((r, score_episode(r, query, weights=weights, trust_score=trust_score)))
    top = sorted(scored, key=lambda x: x[1], reverse=True)[:k]
    return [{"id": r[0], "text": r[2], "score": s} for r, s in top]
