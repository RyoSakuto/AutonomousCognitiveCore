from __future__ import annotations

from typing import Dict, List, Optional

from core.coordinator import Coordinator
from core.domain import TaskSpec
from modules.emotion import AffectSensingModule
from modules.logic import PlanningModule
from modules.nlp import SemanticRetrievalModule
from modules.topic import TopicClusteringModule

_coordinator: Optional[Coordinator] = None
_modules_registered = False


def _get_coordinator() -> Coordinator:
    global _coordinator, _modules_registered
    if _coordinator is None:
        _coordinator = Coordinator()
    if not _modules_registered:
        _coordinator.register_module(AffectSensingModule())
        _coordinator.register_module(SemanticRetrievalModule())
        _coordinator.register_module(PlanningModule())
        _coordinator.register_module(TopicClusteringModule())
        _modules_registered = True
    _coordinator.boot()
    return _coordinator


def boot() -> None:
    coord = _get_coordinator()
    print("✅ NIMCF coordinator initialized with modules:")
    for module in coord.registry.modules:
        meta = module.describe()
        capability_str = ", ".join(meta["capabilities"]) or "-"
        print(f"  • {meta['name']} ({capability_str})")


def add_experience(observation: object, affect_hint: Optional[Dict[str, float]] = None) -> Dict[str, object]:
    coord = _get_coordinator()
    source = "user"
    importance: Optional[float] = None
    metadata: Dict[str, object] = {}
    payload_extras: Dict[str, object] = {}

    obs_text: str
    if isinstance(observation, dict):
        obs_text = str(observation.get("text", "")).strip()
        if not obs_text:
            raise ValueError("Observation dictionary requires a non-empty 'text' field.")
        source = str(observation.get("source", source))
        importance = observation.get("importance")
        metadata = dict(observation.get("metadata") or {})
        payload_extras = dict(observation.get("context") or {})
        if "affect" in observation:
            obs_affect = observation["affect"]
            if isinstance(obs_affect, dict):
                merged = dict(affect_hint or {})
                merged.update({k: obs_affect[k] for k in ("valenz", "arousal") if k in obs_affect})
                affect_hint = merged or None
    else:
        obs_text = str(observation)

    extra_metadata: Dict[str, object] = {}
    if isinstance(affect_hint, dict) and not any(k in affect_hint for k in ("valenz", "arousal")):
        extra_metadata = dict(affect_hint)
        affect_hint = None

    if extra_metadata:
        metadata = {**metadata, **extra_metadata}

    decision = coord.preview_observation(obs_text)
    if decision.decision == "block":
        return coord.store_observation(
            obs_text,
            affect_hint=affect_hint,
            importance=importance,
            source=source,
            policy_decision=decision,
        )
    processed_text = decision.text
    payload = {"text": processed_text}
    if payload_extras:
        payload.update(payload_extras)
    if metadata:
        payload["metadata"] = metadata
    task = TaskSpec(
        goal="affect-annotate",
        payload=payload,
        capabilities={"affect", "observation"},
    )
    coord.submit_task(task, max_modules=1)
    entry = coord.store_observation(
        processed_text,
        affect_hint=affect_hint,
        importance=importance,
        source=source,
        policy_decision=decision,
    )
    if metadata:
        entry.setdefault("metadata", metadata)
    if payload_extras:
        entry.setdefault("context", payload_extras)
    return entry


def query_memory(prompt: str, k: int = 5) -> List[Dict[str, object]]:
    coord = _get_coordinator()
    return coord.recall(prompt, k=k)


def run_task(goal: str, payload: Optional[Dict[str, object]] = None, capabilities: Optional[List[str]] = None):
    coord = _get_coordinator()
    task = TaskSpec(goal=goal, payload=payload or {}, capabilities=set(capabilities or []))
    return coord.submit_task(task)


def inspect_cognitive_map(module: Optional[str] = None, limit: int = 5):
    coord = _get_coordinator()
    if module:
        return coord.module_relations(module, limit=limit)
    return coord.cognitive_snapshot()


def cluster_memory(limit: int = 50):
    coord = _get_coordinator()
    task = TaskSpec(
        goal="Topic Cluster",
        payload={"limit": limit},
        capabilities={"topic-cluster"},
        metadata={"limit": limit},
    )
    return coord.submit_task(task, max_modules=1)


def get_safety_log(limit: int = 20):
    coord = _get_coordinator()
    return coord.safety_log(limit=limit)
