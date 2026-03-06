from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class ACCConfig:
    db_path: str = "data/acc.db"
    max_cycles: int = 6
    tick_interval_sec: float = 0.0

    uncertainty_threshold: float = 0.62
    conflict_threshold: float = 0.55
    novelty_threshold: float = 0.60
    exploration_factor: float = 0.35

    llm_provider: str = "none"
    llm_model: str = "llama3.1"
    llm_endpoint: str = "http://localhost:11434/api/generate"
    llm_timeout_sec: float = 20.0
    llm_api_key: str = ""
    llm_auto_discover: bool = True
    llm_auto_load: bool = False
    llm_prefer_loaded: bool = True
    llm_load_timeout_sec: float = 120.0
    llm_switch_budget: int = 1
    llm_planner_model: str = ""
    llm_reviewer_model: str = ""
    llm_chat_model: str = ""

    embedding_provider: str = "hash"
    embedding_model: str = "nomic-embed-text"
    embedding_endpoint: str = "http://localhost:11434/api/embeddings"
    embedding_dimensions: int = 96
    memory_retrieval_k: int = 4
    memory_candidate_window: int = 400
    memory_min_score: float = 0.15

    self_mod_enabled: bool = True
    self_mod_min_cycles_between_changes: int = 3
    self_mod_rollback_window: int = 3
    self_mod_regression_margin: float = 0.08
    self_mod_budget_window_cycles: int = 20
    self_mod_max_approved_per_window: int = 2
    self_mod_allow_params: str = ""
    self_mod_deny_params: str = ""
    self_mod_rollback_alert_window: int = 24
    self_mod_rollback_alert_threshold: int = 3

    daemon_interval_sec: float = 5.0
    daemon_cycles_per_tick: int = 4

    operating_mode: str = "balanced"
    worker_allowlist: str = ""
    worker_denylist: str = ""

    task_funnel_enabled: bool = True
    task_funnel_batch_size: int = 2
    task_human_feedback_gate: bool = False
    task_execution_enabled: bool = True
    task_execution_batch_size: int = 1
    task_dependency_enforcement: bool = True
    task_retry_default_max_retries: int = 1
    task_retry_default_backoff_sec: int = 0
    task_external_rework_auto_requeue: bool = True
    worker_stats_window_runs: int = 80

    kidiekiruft_root: str = "KIdieKIruft"
    kidiekiruft_live_dispatch_enabled: bool = False
    kidiekiruft_worker_cmd: str = ""
    kidiekiruft_worker_bin: str = ""
    kidiekiruft_worker_timeout_sec: int = 900

    service_lock_path: str = "data/acc_daemon.lock"
    structured_logging_enabled: bool = False
    structured_log_path: str = "data/acc_service.log.jsonl"
    health_server_enabled: bool = False
    health_server_host: str = "127.0.0.1"
    health_server_port: int = 8765

    @staticmethod
    def _parse_bool(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def _field_defaults(cls) -> dict[str, object]:
        return {item.name: item.default for item in fields(cls)}

    @classmethod
    def _convert_value(cls, key: str, raw: object, default: object) -> object:
        if isinstance(raw, str):
            value = raw.strip()
        else:
            value = raw

        if isinstance(default, bool):
            return cls._parse_bool(str(value))
        if isinstance(default, int) and not isinstance(default, bool):
            return int(str(value))
        if isinstance(default, float):
            return float(str(value))
        return str(value)

    @classmethod
    def _overlay(cls, base: dict[str, object], values: dict[str, object]) -> dict[str, object]:
        merged = dict(base)
        defaults = cls._field_defaults()
        for key, raw in values.items():
            if key not in defaults or raw is None:
                continue
            merged[key] = cls._convert_value(key, raw, defaults[key])
        return merged

    @classmethod
    def from_ini_paths(cls, paths: list[str] | None = None) -> "ACCConfig":
        defaults = cls._field_defaults()
        parser = configparser.ConfigParser()
        parser.optionxform = str

        resolved_paths: list[str] = []
        for raw_path in paths or []:
            candidate = Path(raw_path)
            if candidate.exists() and candidate.is_file():
                resolved_paths.append(str(candidate))

        if not resolved_paths:
            return cls(**defaults)

        parser.read(resolved_paths, encoding="utf-8")

        merged = dict(defaults)
        if parser.has_section("acc"):
            merged = cls._overlay(merged, dict(parser.items("acc")))
        return cls(**merged)

    @classmethod
    def default_ini_paths(cls) -> list[str]:
        return ["config/acc.ini", "config/acc.local.ini"]

    @classmethod
    def from_env(cls) -> "ACCConfig":
        defaults = cls._field_defaults()
        return cls(**cls._overlay(defaults, cls._env_overrides(defaults)))

    @classmethod
    def _env_overrides(cls, defaults: dict[str, object] | None = None) -> dict[str, object]:
        base_defaults = defaults or cls._field_defaults()
        env_map = {
            "db_path": "ACC_DB_PATH",
            "max_cycles": "ACC_MAX_CYCLES",
            "tick_interval_sec": "ACC_TICK_INTERVAL",
            "uncertainty_threshold": "ACC_UNCERTAINTY_THRESHOLD",
            "conflict_threshold": "ACC_CONFLICT_THRESHOLD",
            "novelty_threshold": "ACC_NOVELTY_THRESHOLD",
            "exploration_factor": "ACC_EXPLORATION_FACTOR",
            "llm_provider": "ACC_LLM_PROVIDER",
            "llm_model": "ACC_LLM_MODEL",
            "llm_endpoint": "ACC_LLM_ENDPOINT",
            "llm_timeout_sec": "ACC_LLM_TIMEOUT",
            "llm_api_key": "ACC_LLM_API_KEY",
            "llm_auto_discover": "ACC_LLM_AUTO_DISCOVER",
            "llm_auto_load": "ACC_LLM_AUTO_LOAD",
            "llm_prefer_loaded": "ACC_LLM_PREFER_LOADED",
            "llm_load_timeout_sec": "ACC_LLM_LOAD_TIMEOUT",
            "llm_switch_budget": "ACC_LLM_SWITCH_BUDGET",
            "llm_planner_model": "ACC_LLM_PLANNER_MODEL",
            "llm_reviewer_model": "ACC_LLM_REVIEWER_MODEL",
            "llm_chat_model": "ACC_LLM_CHAT_MODEL",
            "embedding_provider": "ACC_EMBEDDING_PROVIDER",
            "embedding_model": "ACC_EMBEDDING_MODEL",
            "embedding_endpoint": "ACC_EMBEDDING_ENDPOINT",
            "embedding_dimensions": "ACC_EMBEDDING_DIMENSIONS",
            "memory_retrieval_k": "ACC_MEMORY_RETRIEVAL_K",
            "memory_candidate_window": "ACC_MEMORY_CANDIDATE_WINDOW",
            "memory_min_score": "ACC_MEMORY_MIN_SCORE",
            "self_mod_enabled": "ACC_SELF_MOD_ENABLED",
            "self_mod_min_cycles_between_changes": "ACC_SELF_MOD_MIN_CYCLES_BETWEEN_CHANGES",
            "self_mod_rollback_window": "ACC_SELF_MOD_ROLLBACK_WINDOW",
            "self_mod_regression_margin": "ACC_SELF_MOD_REGRESSION_MARGIN",
            "self_mod_budget_window_cycles": "ACC_SELF_MOD_BUDGET_WINDOW_CYCLES",
            "self_mod_max_approved_per_window": "ACC_SELF_MOD_MAX_APPROVED_PER_WINDOW",
            "self_mod_allow_params": "ACC_SELF_MOD_ALLOW_PARAMS",
            "self_mod_deny_params": "ACC_SELF_MOD_DENY_PARAMS",
            "self_mod_rollback_alert_window": "ACC_SELF_MOD_ROLLBACK_ALERT_WINDOW",
            "self_mod_rollback_alert_threshold": "ACC_SELF_MOD_ROLLBACK_ALERT_THRESHOLD",
            "daemon_interval_sec": "ACC_DAEMON_INTERVAL_SEC",
            "daemon_cycles_per_tick": "ACC_DAEMON_CYCLES_PER_TICK",
            "operating_mode": "ACC_OPERATING_MODE",
            "worker_allowlist": "ACC_WORKER_ALLOWLIST",
            "worker_denylist": "ACC_WORKER_DENYLIST",
            "task_funnel_enabled": "ACC_TASK_FUNNEL_ENABLED",
            "task_funnel_batch_size": "ACC_TASK_FUNNEL_BATCH_SIZE",
            "task_human_feedback_gate": "ACC_TASK_HUMAN_FEEDBACK_GATE",
            "task_execution_enabled": "ACC_TASK_EXECUTION_ENABLED",
            "task_execution_batch_size": "ACC_TASK_EXECUTION_BATCH_SIZE",
            "task_dependency_enforcement": "ACC_TASK_DEPENDENCY_ENFORCEMENT",
            "task_retry_default_max_retries": "ACC_TASK_RETRY_DEFAULT_MAX_RETRIES",
            "task_retry_default_backoff_sec": "ACC_TASK_RETRY_DEFAULT_BACKOFF_SEC",
            "task_external_rework_auto_requeue": "ACC_TASK_EXTERNAL_REWORK_AUTO_REQUEUE",
            "worker_stats_window_runs": "ACC_WORKER_STATS_WINDOW_RUNS",
            "kidiekiruft_root": "ACC_KIDIEKIRUFT_ROOT",
            "kidiekiruft_live_dispatch_enabled": "ACC_KIDIEKIRUFT_LIVE_DISPATCH_ENABLED",
            "kidiekiruft_worker_cmd": "ACC_KIDIEKIRUFT_WORKER_CMD",
            "kidiekiruft_worker_bin": "ACC_KIDIEKIRUFT_WORKER_BIN",
            "kidiekiruft_worker_timeout_sec": "ACC_KIDIEKIRUFT_WORKER_TIMEOUT_SEC",
            "service_lock_path": "ACC_SERVICE_LOCK_PATH",
            "structured_logging_enabled": "ACC_STRUCTURED_LOGGING_ENABLED",
            "structured_log_path": "ACC_STRUCTURED_LOG_PATH",
            "health_server_enabled": "ACC_HEALTH_SERVER_ENABLED",
            "health_server_host": "ACC_HEALTH_SERVER_HOST",
            "health_server_port": "ACC_HEALTH_SERVER_PORT",
        }

        overrides: dict[str, object] = {}
        for key, env_name in env_map.items():
            raw = os.getenv(env_name)
            if raw is None:
                continue
            overrides[key] = cls._convert_value(key, raw, base_defaults[key])
        return overrides

    @classmethod
    def from_sources(cls, config_paths: list[str] | None = None) -> "ACCConfig":
        base = cls.from_ini_paths(config_paths or cls.default_ini_paths())
        merged = cls._overlay(base.__dict__, cls._env_overrides(cls._field_defaults()))
        return cls(**merged)
