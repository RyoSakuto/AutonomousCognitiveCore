import importlib

import memory.db as db
from core import api


def test_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nimcf.db", raising=False)

    importlib.reload(api)
    api.boot()

    api.add_experience("Testeintrag zum Solarspeicher.", {"valenz": 0.3, "arousal": 0.4})
    hits = api.query_memory("Solarspeicher", k=3)

    assert hits, "Coordinator should return at least one memory hit."
    assert any("Solarspeicher" in hit["text"] for hit in hits)

    plan = api.run_task("Diagnose Solarspeicher", capabilities=["plan", "memory-search"])
    assert plan, "Coordinator should engage modules for planning task."

    clusters = api.cluster_memory(limit=5)
    assert clusters, "Topic clustering module should provide output."

    log = api.get_safety_log(limit=5)
    assert isinstance(log, list)

    entry = api.add_experience(
        {"text": "Heute habe ich ein Sicherheitssystem getestet.", "source": "sensor", "importance": 7.0},
        {"entities": [("topic", "security")]},
    )
    assert entry.get("source") == "sensor"
    assert "metadata" in entry and entry["metadata"].get("entities")
    hits = api.query_memory("Sicherheitssystem", k=3)
    assert any("Sicherheitssystem" in hit["text"] for hit in hits)
