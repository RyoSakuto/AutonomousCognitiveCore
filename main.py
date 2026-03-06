from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from acc import ACCConfig, ACCOrchestrator
from acc.service_runtime import HealthServer, SingleInstanceLock, StructuredLogger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous Cognitive Core MVP")
    parser.add_argument("--cycles", type=int, default=None, help="Number of autonomous cycles")
    parser.add_argument("--db-path", type=str, default=None, help="SQLite database path")
    parser.add_argument(
        "--llm-provider",
        type=str,
        default=None,
        help="none, ollama, openai_compatible (alias: openai, lmstudio)",
    )
    parser.add_argument("--llm-model", type=str, default=None, help="Local LLM model name")
    parser.add_argument("--llm-endpoint", type=str, default=None, help="Local LLM HTTP endpoint")
    parser.add_argument("--llm-timeout", type=float, default=None, help="LLM request timeout in seconds")
    parser.add_argument("--llm-api-key", type=str, default=None, help="Optional API key for LLM endpoint")
    parser.add_argument(
        "--operating-mode",
        type=str,
        default=None,
        help="Operating mode: discovery|balanced|guarded|production",
    )
    parser.add_argument("--embedding-provider", type=str, default=None, help="hash or ollama")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model name")
    parser.add_argument("--embedding-endpoint", type=str, default=None, help="Embedding HTTP endpoint")
    parser.add_argument("--disable-self-mod", action="store_true", help="Disable self-modification layer")
    parser.add_argument(
        "--self-mod-budget-window",
        type=int,
        default=None,
        help="Cycle window for self-mod approval budget",
    )
    parser.add_argument(
        "--self-mod-max-approved",
        type=int,
        default=None,
        help="Max approved self-mod proposals inside budget window",
    )
    parser.add_argument(
        "--self-mod-allow-params",
        type=str,
        default=None,
        help="Comma list of self-mod allowed params override",
    )
    parser.add_argument(
        "--self-mod-deny-params",
        type=str,
        default=None,
        help="Comma list of self-mod denied params override",
    )
    parser.add_argument(
        "--self-mod-rollback-alert-window",
        type=int,
        default=None,
        help="Cycle window for rollback alert aggregation",
    )
    parser.add_argument(
        "--self-mod-rollback-alert-threshold",
        type=int,
        default=None,
        help="Rollback count threshold for warning alert",
    )
    parser.add_argument("--daemon", action="store_true", help="Run continuously in daemon mode")
    parser.add_argument("--daemon-interval", type=float, default=None, help="Seconds between daemon ticks")
    parser.add_argument("--daemon-cycles-per-tick", type=int, default=None, help="Cycles per daemon tick")
    parser.add_argument("--daemon-max-ticks", type=int, default=None, help="Optional max daemon ticks")
    parser.add_argument("--daemon-lock-path", type=str, default=None, help="Lock file path for daemon mode")
    parser.add_argument("--structured-logs", action="store_true", help="Enable structured JSONL service logs")
    parser.add_argument("--structured-log-path", type=str, default=None, help="Structured JSONL log path")
    parser.add_argument("--health-server", action="store_true", help="Enable local HTTP health endpoint")
    parser.add_argument("--health-host", type=str, default=None, help="Health endpoint host")
    parser.add_argument("--health-port", type=int, default=None, help="Health endpoint port")
    parser.add_argument("--ask", type=str, default=None, help="Single natural-language request for ACC")
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode with ACC")
    parser.add_argument("--session-id", type=str, default="default", help="Conversation session identifier")
    parser.add_argument(
        "--plan-goal",
        type=str,
        default=None,
        help="Create a task plan with dependencies from a natural-language goal",
    )
    parser.add_argument(
        "--plan-default-status",
        type=str,
        default="creative",
        help="Default status for planner-created tasks (idea|creative|queued)",
    )
    parser.add_argument(
        "--plan-base-priority",
        type=float,
        default=0.82,
        help="Base priority used by --plan-goal",
    )
    parser.add_argument("--disable-task-funnel", action="store_true", help="Disable task funnel automation")
    parser.add_argument("--disable-task-execution", action="store_true", help="Disable queued task execution")
    parser.add_argument(
        "--task-human-gate",
        action="store_true",
        help="Require human approval before creative tasks become queued",
    )
    parser.add_argument("--task-funnel-batch", type=int, default=None, help="Tasks per stage per cycle")
    parser.add_argument("--task-exec-batch", type=int, default=None, help="Queued tasks executed per cycle")
    parser.add_argument(
        "--task-funnel-now",
        action="store_true",
        help="Run one task-funnel transition pass and exit",
    )
    parser.add_argument(
        "--execute-queue-now",
        action="store_true",
        help="Run one queued-task execution pass and exit",
    )
    parser.add_argument(
        "--sync-kidiekiruft-now",
        action="store_true",
        help="Sync blocked kidiekiruft tasks from external review state and exit",
    )
    parser.add_argument("--list-tasks", type=str, default=None, help="List tasks (status or 'all')")
    parser.add_argument("--task-limit", type=int, default=20, help="Task listing limit")
    parser.add_argument("--approve-task", type=str, default=None, help="Approve blocked task by id or task_key")
    parser.add_argument("--reject-task", type=str, default=None, help="Reject blocked task by id or task_key")
    parser.add_argument(
        "--feedback",
        type=str,
        default="",
        help="Optional feedback text for task approval/rejection",
    )
    parser.add_argument("--create-task", type=str, default=None, help="Create task with this description")
    parser.add_argument("--task-title", type=str, default=None, help="Optional title when creating a task")
    parser.add_argument("--task-status", type=str, default="idea", help="Initial status for --create-task")
    parser.add_argument("--task-priority", type=float, default=0.75, help="Priority for --create-task")
    parser.add_argument("--task-source", type=str, default="external:cli", help="Source for --create-task")
    parser.add_argument(
        "--depends-on",
        action="append",
        default=None,
        help="Task dependency reference (id or task_key). Can be used multiple times.",
    )
    parser.add_argument(
        "--dependency-type",
        type=str,
        default="hard",
        help="Dependency type for --depends-on (hard|soft)",
    )
    parser.add_argument(
        "--task-max-retries",
        type=int,
        default=None,
        help="Max retries for this task (stored in task context)",
    )
    parser.add_argument(
        "--task-retry-backoff",
        type=int,
        default=None,
        help="Retry backoff in seconds per retry attempt",
    )
    parser.add_argument(
        "--task-retry-on",
        type=str,
        default=None,
        help="Comma-separated statuses that trigger retry (e.g. failed,rework)",
    )
    parser.add_argument(
        "--task-worker",
        type=str,
        default=None,
        help="Optional worker route for task creation (acc|nimcf|kidiekiruft)",
    )
    parser.add_argument(
        "--worker-allowlist",
        type=str,
        default=None,
        help="Comma list of allowed workers (acc,nimcf,kidiekiruft)",
    )
    parser.add_argument(
        "--worker-denylist",
        type=str,
        default=None,
        help="Comma list of denied workers (acc,nimcf,kidiekiruft)",
    )
    parser.add_argument(
        "--kidiekiruft-root",
        type=str,
        default=None,
        help="Optional path to KIdieKIruft repository for routed execution",
    )
    parser.add_argument(
        "--kidiekiruft-live-dispatch",
        action="store_true",
        help="Enable real (non-dry-run) dispatch for kidiekiruft worker routing",
    )
    parser.add_argument(
        "--kidiekiruft-worker-cmd",
        type=str,
        default=None,
        help="Override WORKER_CMD passed to KIdieKIruft live dispatch",
    )
    parser.add_argument(
        "--kidiekiruft-worker-bin",
        type=str,
        default=None,
        help="Optional WORKER_BIN passed to KIdieKIruft live dispatch",
    )
    parser.add_argument(
        "--kidiekiruft-timeout",
        type=int,
        default=None,
        help="Worker timeout (seconds) for KIdieKIruft live dispatch",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ACCConfig.from_env()

    if args.db_path:
        config = ACCConfig(**{**config.__dict__, "db_path": args.db_path})
    if args.llm_provider:
        config = ACCConfig(**{**config.__dict__, "llm_provider": args.llm_provider})
    if args.llm_model:
        config = ACCConfig(**{**config.__dict__, "llm_model": args.llm_model})
    if args.llm_endpoint:
        config = ACCConfig(**{**config.__dict__, "llm_endpoint": args.llm_endpoint})
    if args.llm_timeout is not None:
        config = ACCConfig(**{**config.__dict__, "llm_timeout_sec": args.llm_timeout})
    if args.llm_api_key is not None:
        config = ACCConfig(**{**config.__dict__, "llm_api_key": args.llm_api_key})
    if args.operating_mode is not None:
        config = ACCConfig(**{**config.__dict__, "operating_mode": args.operating_mode})
    if args.embedding_provider:
        config = ACCConfig(**{**config.__dict__, "embedding_provider": args.embedding_provider})
    if args.embedding_model:
        config = ACCConfig(**{**config.__dict__, "embedding_model": args.embedding_model})
    if args.embedding_endpoint:
        config = ACCConfig(**{**config.__dict__, "embedding_endpoint": args.embedding_endpoint})
    if args.disable_self_mod:
        config = ACCConfig(**{**config.__dict__, "self_mod_enabled": False})
    if args.self_mod_budget_window is not None:
        config = ACCConfig(
            **{**config.__dict__, "self_mod_budget_window_cycles": args.self_mod_budget_window}
        )
    if args.self_mod_max_approved is not None:
        config = ACCConfig(
            **{**config.__dict__, "self_mod_max_approved_per_window": args.self_mod_max_approved}
        )
    if args.self_mod_allow_params is not None:
        config = ACCConfig(**{**config.__dict__, "self_mod_allow_params": args.self_mod_allow_params})
    if args.self_mod_deny_params is not None:
        config = ACCConfig(**{**config.__dict__, "self_mod_deny_params": args.self_mod_deny_params})
    if args.self_mod_rollback_alert_window is not None:
        config = ACCConfig(
            **{
                **config.__dict__,
                "self_mod_rollback_alert_window": args.self_mod_rollback_alert_window,
            }
        )
    if args.self_mod_rollback_alert_threshold is not None:
        config = ACCConfig(
            **{
                **config.__dict__,
                "self_mod_rollback_alert_threshold": args.self_mod_rollback_alert_threshold,
            }
        )
    if args.disable_task_funnel:
        config = ACCConfig(**{**config.__dict__, "task_funnel_enabled": False})
    if args.disable_task_execution:
        config = ACCConfig(**{**config.__dict__, "task_execution_enabled": False})
    if args.task_human_gate:
        config = ACCConfig(**{**config.__dict__, "task_human_feedback_gate": True})
    if args.task_funnel_batch is not None:
        config = ACCConfig(**{**config.__dict__, "task_funnel_batch_size": args.task_funnel_batch})
    if args.task_exec_batch is not None:
        config = ACCConfig(**{**config.__dict__, "task_execution_batch_size": args.task_exec_batch})
    if args.kidiekiruft_root is not None:
        config = ACCConfig(**{**config.__dict__, "kidiekiruft_root": args.kidiekiruft_root})
    if args.kidiekiruft_live_dispatch:
        config = ACCConfig(**{**config.__dict__, "kidiekiruft_live_dispatch_enabled": True})
    if args.kidiekiruft_worker_cmd is not None:
        config = ACCConfig(**{**config.__dict__, "kidiekiruft_worker_cmd": args.kidiekiruft_worker_cmd})
    if args.kidiekiruft_worker_bin is not None:
        config = ACCConfig(**{**config.__dict__, "kidiekiruft_worker_bin": args.kidiekiruft_worker_bin})
    if args.kidiekiruft_timeout is not None:
        config = ACCConfig(
            **{**config.__dict__, "kidiekiruft_worker_timeout_sec": args.kidiekiruft_timeout}
        )
    if args.worker_allowlist is not None:
        config = ACCConfig(**{**config.__dict__, "worker_allowlist": args.worker_allowlist})
    if args.worker_denylist is not None:
        config = ACCConfig(**{**config.__dict__, "worker_denylist": args.worker_denylist})
    if args.daemon_lock_path is not None:
        config = ACCConfig(**{**config.__dict__, "service_lock_path": args.daemon_lock_path})
    if args.structured_logs:
        config = ACCConfig(**{**config.__dict__, "structured_logging_enabled": True})
    if args.structured_log_path is not None:
        config = ACCConfig(**{**config.__dict__, "structured_log_path": args.structured_log_path})
    if args.health_server:
        config = ACCConfig(**{**config.__dict__, "health_server_enabled": True})
    if args.health_host is not None:
        config = ACCConfig(**{**config.__dict__, "health_server_host": args.health_host})
    if args.health_port is not None:
        config = ACCConfig(**{**config.__dict__, "health_server_port": args.health_port})
    if args.daemon_interval is not None:
        config = ACCConfig(**{**config.__dict__, "daemon_interval_sec": args.daemon_interval})
    if args.daemon_cycles_per_tick is not None:
        config = ACCConfig(**{**config.__dict__, "daemon_cycles_per_tick": args.daemon_cycles_per_tick})

    logger = StructuredLogger(
        enabled=config.structured_logging_enabled,
        path=config.structured_log_path,
    )
    daemon_lock: SingleInstanceLock | None = None
    health_server: HealthServer | None = None
    health_state: dict[str, object] = {
        "mode": "booting",
        "tick": 0,
        "last_run_at": None,
        "last_error": None,
        "db_path": config.db_path,
        "pid": None,
    }

    if args.daemon:
        daemon_lock = SingleInstanceLock(config.service_lock_path)
        try:
            daemon_lock.acquire()
        except RuntimeError as exc:
            print(f"Error: {exc}")
            return
        health_state["pid"] = "locked"
        logger.emit("daemon_lock_acquired", lock_path=config.service_lock_path)

    orchestrator: ACCOrchestrator | None = None
    try:
        orchestrator = ACCOrchestrator(config)
        logger.emit(
            "acc_process_start",
            daemon=args.daemon,
            db_path=config.db_path,
            llm_provider=config.llm_provider,
            llm_model=config.llm_model,
            operating_mode=config.operating_mode,
        )
        if config.health_server_enabled:
            def _health_payload() -> dict:
                return {
                    "ok": True,
                    "service": "acc",
                    "mode": health_state.get("mode"),
                    "tick": health_state.get("tick"),
                    "last_run_at": health_state.get("last_run_at"),
                    "last_error": health_state.get("last_error"),
                    "db_path": health_state.get("db_path"),
                }

            health_server = HealthServer(
                host=config.health_server_host,
                port=max(1, int(config.health_server_port)),
                provider=_health_payload,
            )
            try:
                health_server.start()
                logger.emit(
                    "health_server_started",
                    host=config.health_server_host,
                    port=max(1, int(config.health_server_port)),
                )
            except Exception as exc:
                health_state["last_error"] = f"health_server_start_failed:{exc}"
                logger.emit(
                    "health_server_start_failed",
                    host=config.health_server_host,
                    port=max(1, int(config.health_server_port)),
                    error=str(exc),
                )
                print(f"Warning: health server could not start ({exc}).")
                health_server = None

        if args.ask is not None and args.daemon:
            print("Error: --ask and --daemon cannot be combined.")
            return
        if args.chat and args.daemon:
            print("Error: --chat and --daemon cannot be combined.")
            return
        if args.plan_goal is not None and args.daemon:
            print("Error: --plan-goal and --daemon cannot be combined.")
            return
        if args.ask is not None and args.chat:
            print("Error: use either --ask or --chat, not both.")
            return
        if args.plan_goal is not None and (args.ask is not None or args.chat):
            print("Error: --plan-goal cannot be combined with --ask/--chat.")
            return
        if args.approve_task and args.reject_task:
            print("Error: use either --approve-task or --reject-task, not both.")
            return
        if args.task_funnel_now and args.daemon:
            print("Error: --task-funnel-now and --daemon cannot be combined.")
            return
        if args.execute_queue_now and args.daemon:
            print("Error: --execute-queue-now and --daemon cannot be combined.")
            return
        if args.sync_kidiekiruft_now and args.daemon:
            print("Error: --sync-kidiekiruft-now and --daemon cannot be combined.")
            return
        if args.task_funnel_now and (args.ask is not None or args.chat):
            print("Error: --task-funnel-now cannot be combined with --ask/--chat.")
            return
        if args.execute_queue_now and (args.ask is not None or args.chat):
            print("Error: --execute-queue-now cannot be combined with --ask/--chat.")
            return
        if args.sync_kidiekiruft_now and (args.ask is not None or args.chat):
            print("Error: --sync-kidiekiruft-now cannot be combined with --ask/--chat.")
            return
        if args.list_tasks is not None and (
            args.ask is not None or args.chat or args.daemon or args.plan_goal is not None
        ):
            print("Error: --list-tasks cannot be combined with --ask/--chat/--daemon/--plan-goal.")
            return
        if args.task_funnel_batch is not None and args.task_funnel_batch < 1:
            print("Error: --task-funnel-batch must be >= 1.")
            return
        if args.task_exec_batch is not None and args.task_exec_batch < 1:
            print("Error: --task-exec-batch must be >= 1.")
            return
        if args.kidiekiruft_timeout is not None and args.kidiekiruft_timeout < 1:
            print("Error: --kidiekiruft-timeout must be >= 1.")
            return
        if args.task_max_retries is not None and args.task_max_retries < 0:
            print("Error: --task-max-retries must be >= 0.")
            return
        if args.task_retry_backoff is not None and args.task_retry_backoff < 0:
            print("Error: --task-retry-backoff must be >= 0.")
            return
        if args.dependency_type.strip().lower() not in {"hard", "soft"}:
            print("Error: --dependency-type must be hard or soft.")
            return
        if args.health_port is not None and args.health_port < 1:
            print("Error: --health-port must be >= 1.")
            return
        if config.operating_mode.strip().lower() not in {"discovery", "balanced", "guarded", "production"}:
            print("Error: --operating-mode must be discovery|balanced|guarded|production.")
            return
        if args.self_mod_budget_window is not None and args.self_mod_budget_window < 1:
            print("Error: --self-mod-budget-window must be >= 1.")
            return
        if args.self_mod_max_approved is not None and args.self_mod_max_approved < 0:
            print("Error: --self-mod-max-approved must be >= 0.")
            return
        if args.self_mod_rollback_alert_window is not None and args.self_mod_rollback_alert_window < 1:
            print("Error: --self-mod-rollback-alert-window must be >= 1.")
            return
        if (
            args.self_mod_rollback_alert_threshold is not None
            and args.self_mod_rollback_alert_threshold < 1
        ):
            print("Error: --self-mod-rollback-alert-threshold must be >= 1.")
            return
        if args.plan_default_status.strip().lower() not in {"idea", "creative", "queued"}:
            print("Error: --plan-default-status must be idea|creative|queued.")
            return
        if not 0.0 <= float(args.plan_base_priority) <= 1.0:
            print("Error: --plan-base-priority must be between 0.0 and 1.0.")
            return

        if args.create_task is not None:
            description = args.create_task.strip()
            if not description:
                print("Error: --create-task requires non-empty text.")
                return
            title = args.task_title.strip() if args.task_title else description[:72]
            task_context: dict[str, object] = {}
            if args.task_worker is not None:
                worker_value = args.task_worker.strip().lower()
                if worker_value not in {"acc", "nimcf", "kidiekiruft"}:
                    print("Error: --task-worker must be one of acc|nimcf|kidiekiruft.")
                    return
                task_context["worker"] = worker_value
            if args.task_max_retries is not None:
                task_context["max_retries"] = args.task_max_retries
            if args.task_retry_backoff is not None:
                task_context["retry_backoff_sec"] = args.task_retry_backoff
            if args.task_retry_on is not None:
                retry_on = [item.strip().lower() for item in args.task_retry_on.split(",") if item.strip()]
                if not retry_on:
                    print("Error: --task-retry-on must contain at least one status token.")
                    return
                task_context["retry_on_statuses"] = retry_on

            dependency_type = args.dependency_type.strip().lower()
            dependency_ids: list[int] = []
            if args.depends_on:
                for dependency_ref in args.depends_on:
                    target = orchestrator.state.resolve_task_reference(dependency_ref)
                    if target is None:
                        print(f"Error: dependency not found: {dependency_ref}")
                        return
                    dependency_ids.append(int(target["id"]))

            task_id = orchestrator.state.create_task(
                title=title,
                description=description,
                source=args.task_source,
                status=args.task_status,
                priority=args.task_priority,
                context=task_context if task_context else None,
            )
            dependency_created = 0
            for dependency_id in dependency_ids:
                orchestrator.state.add_task_dependency(
                    task_id=task_id,
                    depends_on_task_id=dependency_id,
                    dependency_type=dependency_type,
                )
                dependency_created += 1

            task = orchestrator.state.get_task(task_id)
            print("ACC task created")
            print(f"task_id={task_id}")
            print(f"task_key={task['task_key'] if task else 'unknown'}")
            print(f"status={task['status'] if task else args.task_status}")
            if "worker" in task_context:
                print(f"worker={task_context['worker']}")
            if dependency_created > 0:
                print(f"dependencies_added={dependency_created}")
                print(f"dependency_type={dependency_type}")
            if "max_retries" in task_context:
                print(f"max_retries={task_context['max_retries']}")
            if "retry_backoff_sec" in task_context:
                print(f"retry_backoff_sec={task_context['retry_backoff_sec']}")
            print(f"title={title}")
            logger.emit(
                "task_created_via_cli",
                task_id=task_id,
                task_key=task["task_key"] if task else None,
                status=task["status"] if task else args.task_status,
                dependency_count=dependency_created,
            )
            return

        if args.plan_goal is not None:
            try:
                plan = orchestrator.plan_goal_to_tasks(
                    goal_text=args.plan_goal,
                    session_id=args.session_id,
                    default_status=args.plan_default_status,
                    base_priority=args.plan_base_priority,
                )
            except ValueError as exc:
                print(f"Error: {exc}")
                return
            print("ACC goal plan created")
            print(f"plan_id={plan['plan_id']}")
            print(f"plan_title={plan['plan_title']}")
            print(f"task_count={plan['task_count']}")
            print(f"dependency_count={plan['dependency_count']}")
            print(f"planner_fallback={str(plan['fallback']).lower()}")
            print(f"source={plan['source']}")
            for item in plan["tasks"]:
                worker = item.get("worker") or "auto"
                depends = ",".join(str(dep) for dep in item.get("depends_on", [])) or "none"
                print(
                    f"{item['task_key']} status={item['status']} worker={worker} "
                    f"depends_on={depends} title={item['title']}"
                )
            logger.emit(
                "goal_plan_created_via_cli",
                plan_id=plan["plan_id"],
                task_count=plan["task_count"],
                dependency_count=plan["dependency_count"],
                fallback=plan["fallback"],
            )
            return

        if args.list_tasks is not None:
            raw = args.list_tasks.strip().lower()
            status = None if raw in {"", "all"} else raw
            tasks = orchestrator.state.list_tasks(status=status, limit=args.task_limit)
            print(f"ACC tasks count={len(tasks)}")
            for task in tasks:
                print(
                    f"{task['task_key']} id={task['id']} status={task['status']} "
                    f"priority={float(task['priority']):.2f} title={task['title']}"
                )
            return

        if args.approve_task is not None:
            try:
                result = orchestrator.review_human_gate_task(
                    task_ref=args.approve_task,
                    approved=True,
                    feedback=args.feedback,
                )
            except ValueError as exc:
                print(f"Error: {exc}")
                return
            print("ACC task approved")
            print(f"task_id={result['task_id']}")
            print(f"task_key={result['task_key']}")
            print(f"status={result['status']}")
            print(f"decision={result['decision']}")
            if result.get("auto_actions"):
                print(f"auto_actions={','.join(result['auto_actions'])}")
            return

        if args.reject_task is not None:
            try:
                result = orchestrator.review_human_gate_task(
                    task_ref=args.reject_task,
                    approved=False,
                    feedback=args.feedback,
                )
            except ValueError as exc:
                print(f"Error: {exc}")
                return
            print("ACC task rejected for rework")
            print(f"task_id={result['task_id']}")
            print(f"task_key={result['task_key']}")
            print(f"status={result['status']}")
            print(f"decision={result['decision']}")
            if result.get("auto_actions"):
                print(f"auto_actions={','.join(result['auto_actions'])}")
            return

        if args.task_funnel_now:
            transitions = orchestrator.process_task_funnel()
            blocked = len(orchestrator.state.list_tasks(status="blocked", limit=200))
            print("ACC task funnel pass complete")
            print(f"funnel_transitions={transitions}")
            print(f"blocked_waiting_human={blocked}")
            logger.emit("task_funnel_once_complete", transitions=transitions, blocked=blocked)
            return

        if args.execute_queue_now:
            executed = orchestrator.process_task_execution()
            queued = len(orchestrator.state.list_tasks(status="queued", limit=500))
            print("ACC queue execution pass complete")
            print(f"executed_tasks={executed}")
            print(f"queued_remaining={queued}")
            logger.emit("queue_execution_once_complete", executed=executed, queued_remaining=queued)
            return

        if args.sync_kidiekiruft_now:
            synced = orchestrator.process_kidiekiruft_sync()
            blocked = len(orchestrator.state.list_tasks(status="blocked", limit=500))
            print("ACC kidiekiruft sync pass complete")
            print(f"synced_tasks={synced}")
            print(f"blocked_remaining={blocked}")
            logger.emit("kidiekiruft_sync_once_complete", synced=synced, blocked_remaining=blocked)
            return

        if args.ask is not None:
            goal_id = orchestrator.submit_external_request(
                user_text=args.ask,
                session_id=args.session_id,
            )
            summary = orchestrator.run(cycles=args.cycles)
            answer = orchestrator.generate_external_response(
                goal_id=goal_id,
                user_text=args.ask,
                session_id=args.session_id,
            )
            print("ACC ask complete")
            print(f"session_id={args.session_id}")
            print(f"goal_id={goal_id}")
            print(f"cycles={summary.cycles}")
            print(f"start_cycle={summary.start_cycle}")
            print(f"end_cycle={summary.end_cycle}")
            print(f"autonomous_tasks={summary.autonomous_tasks}")
            print(f"avg_uncertainty={summary.avg_uncertainty:.3f}")
            print(f"db={summary.db_path}")
            print("answer:")
            print(answer)
            health_state["mode"] = "ask"
            health_state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            logger.emit(
                "ask_complete",
                session_id=args.session_id,
                goal_id=goal_id,
                cycles=summary.cycles,
                avg_uncertainty=round(summary.avg_uncertainty, 4),
            )
            return

        if args.chat:
            print("ACC chat gestartet. Beenden mit 'exit' oder 'quit'.")
            while True:
                try:
                    user_text = input("Du> ").strip()
                except EOFError:
                    print("\nACC chat beendet (EOF).")
                    break
                except KeyboardInterrupt:
                    print("\nACC chat beendet (Interrupt).")
                    break

                if not user_text:
                    continue
                if user_text.lower() in {"exit", "quit"}:
                    print("ACC chat beendet.")
                    break

                goal_id = orchestrator.submit_external_request(
                    user_text=user_text,
                    session_id=args.session_id,
                )
                summary = orchestrator.run(cycles=args.cycles)
                answer = orchestrator.generate_external_response(
                    goal_id=goal_id,
                    user_text=user_text,
                    session_id=args.session_id,
                )
                print(
                    f"ACC> {answer}\n"
                    f"[session={args.session_id} cycles={summary.start_cycle}-{summary.end_cycle} "
                    f"avg_u={summary.avg_uncertainty:.3f}]"
                )
                health_state["mode"] = "chat"
                health_state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                logger.emit(
                    "chat_turn_complete",
                    session_id=args.session_id,
                    goal_id=goal_id,
                    cycles=summary.cycles,
                    avg_uncertainty=round(summary.avg_uncertainty, 4),
                )
            return

        if not args.daemon:
            summary = orchestrator.run(cycles=args.cycles)
            print("ACC run complete")
            print(f"cycles={summary.cycles}")
            print(f"start_cycle={summary.start_cycle}")
            print(f"end_cycle={summary.end_cycle}")
            print(f"autonomous_tasks={summary.autonomous_tasks}")
            print(f"avg_uncertainty={summary.avg_uncertainty:.3f}")
            print(f"db={summary.db_path}")
            health_state["mode"] = "run_once"
            health_state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            logger.emit(
                "run_once_complete",
                cycles=summary.cycles,
                start_cycle=summary.start_cycle,
                end_cycle=summary.end_cycle,
                autonomous_tasks=summary.autonomous_tasks,
                avg_uncertainty=round(summary.avg_uncertainty, 4),
            )
            return

        health_state["mode"] = "daemon"
        tick = 0
        while True:
            tick += 1
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            summary = orchestrator.run(cycles=config.daemon_cycles_per_tick)
            print(
                f"[{now}] daemon_tick={tick} "
                f"cycles={summary.cycles} range={summary.start_cycle}-{summary.end_cycle} "
                f"autonomous_tasks={summary.autonomous_tasks} avg_uncertainty={summary.avg_uncertainty:.3f}"
            )
            health_state["tick"] = tick
            health_state["last_run_at"] = now
            logger.emit(
                "daemon_tick_complete",
                tick=tick,
                cycles=summary.cycles,
                start_cycle=summary.start_cycle,
                end_cycle=summary.end_cycle,
                autonomous_tasks=summary.autonomous_tasks,
                avg_uncertainty=round(summary.avg_uncertainty, 4),
            )

            if args.daemon_max_ticks is not None and tick >= args.daemon_max_ticks:
                break

            if config.daemon_interval_sec > 0:
                time.sleep(config.daemon_interval_sec)
        print("ACC daemon complete")
        print(f"ticks={tick}")
        print(f"db={config.db_path}")
        logger.emit("daemon_complete", ticks=tick, db_path=config.db_path)
    except KeyboardInterrupt:
        health_state["last_error"] = "keyboard_interrupt"
        print("ACC daemon interrupted")
        logger.emit("daemon_interrupted")
    finally:
        if health_server is not None:
            health_server.stop()
            logger.emit("health_server_stopped")
        if orchestrator is not None:
            orchestrator.close()
        if daemon_lock is not None:
            daemon_lock.release()
            logger.emit("daemon_lock_released", lock_path=config.service_lock_path)
        logger.emit("acc_process_stop")


if __name__ == "__main__":
    main()
