from __future__ import annotations

import os
from dataclasses import dataclass


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
    def from_env(cls) -> "ACCConfig":
        def _get(name: str, default: str) -> str:
            return os.getenv(name, default)

        return cls(
            db_path=_get("ACC_DB_PATH", cls.db_path),
            max_cycles=int(_get("ACC_MAX_CYCLES", str(cls.max_cycles))),
            tick_interval_sec=float(_get("ACC_TICK_INTERVAL", str(cls.tick_interval_sec))),
            uncertainty_threshold=float(_get("ACC_UNCERTAINTY_THRESHOLD", str(cls.uncertainty_threshold))),
            conflict_threshold=float(_get("ACC_CONFLICT_THRESHOLD", str(cls.conflict_threshold))),
            novelty_threshold=float(_get("ACC_NOVELTY_THRESHOLD", str(cls.novelty_threshold))),
            exploration_factor=float(_get("ACC_EXPLORATION_FACTOR", str(cls.exploration_factor))),
            llm_provider=_get("ACC_LLM_PROVIDER", cls.llm_provider),
            llm_model=_get("ACC_LLM_MODEL", cls.llm_model),
            llm_endpoint=_get("ACC_LLM_ENDPOINT", cls.llm_endpoint),
            llm_timeout_sec=float(_get("ACC_LLM_TIMEOUT", str(cls.llm_timeout_sec))),
            llm_api_key=_get("ACC_LLM_API_KEY", cls.llm_api_key),
            embedding_provider=_get("ACC_EMBEDDING_PROVIDER", cls.embedding_provider),
            embedding_model=_get("ACC_EMBEDDING_MODEL", cls.embedding_model),
            embedding_endpoint=_get("ACC_EMBEDDING_ENDPOINT", cls.embedding_endpoint),
            embedding_dimensions=int(_get("ACC_EMBEDDING_DIMENSIONS", str(cls.embedding_dimensions))),
            memory_retrieval_k=int(_get("ACC_MEMORY_RETRIEVAL_K", str(cls.memory_retrieval_k))),
            memory_candidate_window=int(
                _get("ACC_MEMORY_CANDIDATE_WINDOW", str(cls.memory_candidate_window))
            ),
            memory_min_score=float(_get("ACC_MEMORY_MIN_SCORE", str(cls.memory_min_score))),
            self_mod_enabled=cls._parse_bool(_get("ACC_SELF_MOD_ENABLED", str(cls.self_mod_enabled))),
            self_mod_min_cycles_between_changes=int(
                _get(
                    "ACC_SELF_MOD_MIN_CYCLES_BETWEEN_CHANGES",
                    str(cls.self_mod_min_cycles_between_changes),
                )
            ),
            self_mod_rollback_window=int(
                _get("ACC_SELF_MOD_ROLLBACK_WINDOW", str(cls.self_mod_rollback_window))
            ),
            self_mod_regression_margin=float(
                _get("ACC_SELF_MOD_REGRESSION_MARGIN", str(cls.self_mod_regression_margin))
            ),
            self_mod_budget_window_cycles=int(
                _get("ACC_SELF_MOD_BUDGET_WINDOW_CYCLES", str(cls.self_mod_budget_window_cycles))
            ),
            self_mod_max_approved_per_window=int(
                _get(
                    "ACC_SELF_MOD_MAX_APPROVED_PER_WINDOW",
                    str(cls.self_mod_max_approved_per_window),
                )
            ),
            self_mod_allow_params=_get("ACC_SELF_MOD_ALLOW_PARAMS", cls.self_mod_allow_params),
            self_mod_deny_params=_get("ACC_SELF_MOD_DENY_PARAMS", cls.self_mod_deny_params),
            self_mod_rollback_alert_window=int(
                _get(
                    "ACC_SELF_MOD_ROLLBACK_ALERT_WINDOW",
                    str(cls.self_mod_rollback_alert_window),
                )
            ),
            self_mod_rollback_alert_threshold=int(
                _get(
                    "ACC_SELF_MOD_ROLLBACK_ALERT_THRESHOLD",
                    str(cls.self_mod_rollback_alert_threshold),
                )
            ),
            daemon_interval_sec=float(_get("ACC_DAEMON_INTERVAL_SEC", str(cls.daemon_interval_sec))),
            daemon_cycles_per_tick=int(
                _get("ACC_DAEMON_CYCLES_PER_TICK", str(cls.daemon_cycles_per_tick))
            ),
            operating_mode=_get("ACC_OPERATING_MODE", cls.operating_mode),
            worker_allowlist=_get("ACC_WORKER_ALLOWLIST", cls.worker_allowlist),
            worker_denylist=_get("ACC_WORKER_DENYLIST", cls.worker_denylist),
            task_funnel_enabled=cls._parse_bool(
                _get("ACC_TASK_FUNNEL_ENABLED", str(cls.task_funnel_enabled))
            ),
            task_funnel_batch_size=int(
                _get("ACC_TASK_FUNNEL_BATCH_SIZE", str(cls.task_funnel_batch_size))
            ),
            task_human_feedback_gate=cls._parse_bool(
                _get("ACC_TASK_HUMAN_FEEDBACK_GATE", str(cls.task_human_feedback_gate))
            ),
            task_execution_enabled=cls._parse_bool(
                _get("ACC_TASK_EXECUTION_ENABLED", str(cls.task_execution_enabled))
            ),
            task_execution_batch_size=int(
                _get("ACC_TASK_EXECUTION_BATCH_SIZE", str(cls.task_execution_batch_size))
            ),
            task_dependency_enforcement=cls._parse_bool(
                _get(
                    "ACC_TASK_DEPENDENCY_ENFORCEMENT",
                    str(cls.task_dependency_enforcement),
                )
            ),
            task_retry_default_max_retries=int(
                _get(
                    "ACC_TASK_RETRY_DEFAULT_MAX_RETRIES",
                    str(cls.task_retry_default_max_retries),
                )
            ),
            task_retry_default_backoff_sec=int(
                _get(
                    "ACC_TASK_RETRY_DEFAULT_BACKOFF_SEC",
                    str(cls.task_retry_default_backoff_sec),
                )
            ),
            task_external_rework_auto_requeue=cls._parse_bool(
                _get(
                    "ACC_TASK_EXTERNAL_REWORK_AUTO_REQUEUE",
                    str(cls.task_external_rework_auto_requeue),
                )
            ),
            worker_stats_window_runs=int(
                _get("ACC_WORKER_STATS_WINDOW_RUNS", str(cls.worker_stats_window_runs))
            ),
            kidiekiruft_root=_get("ACC_KIDIEKIRUFT_ROOT", cls.kidiekiruft_root),
            kidiekiruft_live_dispatch_enabled=cls._parse_bool(
                _get(
                    "ACC_KIDIEKIRUFT_LIVE_DISPATCH_ENABLED",
                    str(cls.kidiekiruft_live_dispatch_enabled),
                )
            ),
            kidiekiruft_worker_cmd=_get("ACC_KIDIEKIRUFT_WORKER_CMD", cls.kidiekiruft_worker_cmd),
            kidiekiruft_worker_bin=_get("ACC_KIDIEKIRUFT_WORKER_BIN", cls.kidiekiruft_worker_bin),
            kidiekiruft_worker_timeout_sec=int(
                _get(
                    "ACC_KIDIEKIRUFT_WORKER_TIMEOUT_SEC",
                    str(cls.kidiekiruft_worker_timeout_sec),
                )
            ),
            service_lock_path=_get("ACC_SERVICE_LOCK_PATH", cls.service_lock_path),
            structured_logging_enabled=cls._parse_bool(
                _get("ACC_STRUCTURED_LOGGING_ENABLED", str(cls.structured_logging_enabled))
            ),
            structured_log_path=_get("ACC_STRUCTURED_LOG_PATH", cls.structured_log_path),
            health_server_enabled=cls._parse_bool(
                _get("ACC_HEALTH_SERVER_ENABLED", str(cls.health_server_enabled))
            ),
            health_server_host=_get("ACC_HEALTH_SERVER_HOST", cls.health_server_host),
            health_server_port=int(_get("ACC_HEALTH_SERVER_PORT", str(cls.health_server_port))),
        )
