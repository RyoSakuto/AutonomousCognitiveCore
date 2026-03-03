from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt

from .db import ACCDatabase
from .embedding import Embedder


@dataclass
class RetrievedMemory:
    id: int
    source_kind: str
    source_id: int
    cycle: int
    text: str
    score: float


class SemanticMemory:
    def __init__(
        self,
        db: ACCDatabase,
        embedder: Embedder,
        candidate_window: int = 400,
    ) -> None:
        self.db = db
        self.embedder = embedder
        self.candidate_window = candidate_window

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sqrt(sum(x * x for x in a))
        norm_b = sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def add_entry(self, cycle: int, source_kind: str, source_id: int, text: str) -> int:
        vector = self.embedder.embed(text)
        now = self._now_iso()
        cur = self.db.conn.execute(
            """
            INSERT INTO memory_embeddings(cycle, source_kind, source_id, text, vector_json, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (cycle, source_kind, source_id, text, json.dumps(vector), now),
        )
        self.db.conn.commit()
        return int(cur.lastrowid)

    def retrieve(self, query: str, top_k: int, min_score: float = 0.15) -> list[RetrievedMemory]:
        if not query.strip() or top_k <= 0:
            return []

        query_vec = self.embedder.embed(query)
        rows = self.db.conn.execute(
            """
            SELECT id, source_kind, source_id, cycle, text, vector_json
            FROM memory_embeddings
            ORDER BY id DESC
            LIMIT ?
            """,
            (self.candidate_window,),
        ).fetchall()

        scored: list[RetrievedMemory] = []
        for row in rows:
            try:
                vec = json.loads(row["vector_json"])
                if not isinstance(vec, list):
                    continue
                candidate_vec = [float(v) for v in vec]
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

            score = self._cosine(query_vec, candidate_vec)
            if score < min_score:
                continue

            scored.append(
                RetrievedMemory(
                    id=int(row["id"]),
                    source_kind=str(row["source_kind"]),
                    source_id=int(row["source_id"]),
                    cycle=int(row["cycle"]),
                    text=str(row["text"]),
                    score=float(score),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]
