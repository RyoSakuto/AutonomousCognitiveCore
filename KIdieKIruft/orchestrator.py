#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("orchestrator")
QUEUE_FILE = ROOT / "queue.json"
RUNS_DIR = ROOT / "runs"

OPEN_STATUSES = {"ready", "rework"}
FATAL_WORKER_PATTERNS = {
    "stream disconnected before completion": "Worker-Stream wurde vor Abschluss getrennt.",
    "does not exist or you do not have access to it": "Konfiguriertes Modell ist nicht verfuegbar oder nicht freigeschaltet.",
    "authentication failed": "Worker-Authentifizierung fehlgeschlagen.",
    "unauthorized": "Worker ist nicht authorisiert.",
}
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")
COMMON_PATH_PREFIXES = {"docs", "src", "scripts", "orchestrator", "tests", "test", "lib", "app", "bin", "config"}
TIMESTAMPED_ERROR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z ERROR\b")
DEFAULT_WORKER_TIMEOUT_SECONDS = 900
DEFAULT_FOLLOWUP_POLICY = "none"
FOLLOWUP_POLICY_VALUES = {"all", "bugfix_only", "none"}
BUGFIX_FOLLOWUP_KEYWORDS = (
    "bug",
    "bugfix",
    "fix",
    "fehler",
    "regression",
    "stabil",
    "stability",
    "hotfix",
    "korrig",
    "repair",
    "route",
    "win-route",
    "wiederher",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_layout() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if not QUEUE_FILE.exists():
        data = {"tasks": [], "history": []}
        QUEUE_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_queue() -> dict:
    ensure_layout()
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(data: dict) -> None:
    QUEUE_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def next_task_id(tasks: list[dict]) -> str:
    return f"TASK-{len(tasks) + 1:03d}"


def find_task(tasks: list[dict], task_id: str) -> dict | None:
    for task in tasks:
        if task["id"] == task_id:
            return task
    return None


def add_history(queue: dict, event: dict) -> None:
    event["timestamp"] = now_iso()
    queue["history"].append(event)


def cmd_init(_: argparse.Namespace) -> int:
    ensure_layout()
    print(f"Initialized orchestrator at {ROOT}")
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    queue = load_queue()
    task = {
        "id": next_task_id(queue["tasks"]),
        "title": args.title,
        "description": args.description,
        "acceptance": args.acceptance or [],
        "status": "ready",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "attempts": 0,
        "last_run": None,
        "review_notes": [],
    }
    queue["tasks"].append(task)
    add_history(queue, {"type": "task_added", "task_id": task["id"], "title": task["title"]})
    save_queue(queue)
    print(f"Added {task['id']}: {task['title']}")
    return 0


def cmd_task_list(args: argparse.Namespace) -> int:
    queue = load_queue()
    filtered = queue["tasks"]
    if args.status:
        filtered = [t for t in filtered if t["status"] == args.status]
    if not filtered:
        print("No tasks found.")
        return 0

    for task in filtered:
        print(f"{task['id']} [{task['status']}] {task['title']}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    queue = load_queue()
    tasks = queue["tasks"]
    history = queue["history"]

    print(f"Tasks total: {len(tasks)}")
    if not tasks:
        print("No tasks found.")
        print("Next:")
        print('- Add task: python3 orchestrator.py task add --title "..." --description "..."')
        return 0

    status_order = ["ready", "rework", "in_progress", "submitted", "approved"]
    counts = {status: 0 for status in status_order}
    for task in tasks:
        status = task["status"]
        if status not in counts:
            counts[status] = 0
        counts[status] += 1

    print("Status counts:")
    for status in status_order:
        print(f"- {status}: {counts.get(status, 0)}")
    extra_statuses = sorted(status for status in counts if status not in status_order)
    for status in extra_statuses:
        print(f"- {status}: {counts.get(status, 0)}")

    open_tasks = [task for task in tasks if task["status"] in OPEN_STATUSES]
    print(f"Dispatchable tasks: {len(open_tasks)}")
    print(f"Follow-up policy: {followup_policy()}")

    next_task = pick_dispatch_task(tasks, task_id=None)
    if next_task:
        print(f"Next dispatchable: {next_task['id']} [{next_task['status']}] {next_task['title']}")
    else:
        print("Next dispatchable: none")

    recently_updated = max(tasks, key=lambda task: task.get("updated_at", ""))
    print(f"Last updated task: {recently_updated['id']} [{recently_updated['status']}]")
    if recently_updated.get("last_run"):
        run_dir = Path(recently_updated["last_run"])
        print(f"Last run dir: {run_dir}")
        print(f"Last run logs: {run_dir / 'stdout.log'} | {run_dir / 'stderr.log'} | {run_dir / 'meta.json'}")

    print(f"History events: {len(history)}")
    if history:
        last_event = history[-1]
        event_type = last_event.get("type", "unknown")
        event_task_id = last_event.get("task_id") or last_event.get("source_task_id")
        event_timestamp = last_event.get("timestamp", "unknown")
        print(f"Last event: {event_type} (task={event_task_id}, at={event_timestamp})")

    print("Resume:")
    if os.environ.get("WORKER_CMD"):
        print("- Optional closeout mode: export ORCH_FOLLOWUP_POLICY='none'")
        print("- Continue queue: python3 orchestrator.py autopilot --max-tasks 1")
    else:
        print("- Set worker cmd: export WORKER_CMD='./scripts/worker_codex.sh {prompt_file}'")
        print("- Optional closeout mode: export ORCH_FOLLOWUP_POLICY='none'")
        print("- Continue queue: WORKER_BIN='gpt' python3 orchestrator.py autopilot --max-tasks 1")
    return 0


def build_worker_prompt(task: dict, run_dir: Path | None = None) -> str:
    acceptance = "\n".join(f"- {line}" for line in task["acceptance"]) or "- Keine angegeben"
    optional_followup = ""
    if run_dir is not None:
        followup_file = run_dir / "followup_tasks.json"
        optional_followup = (
            "- Optional: Wenn sinnvoll, plane Folge-Tasks und speichere sie als JSON-Liste in\n"
            f"  `{followup_file}` im Format:\n"
            '  `[{"title":"...","description":"...","acceptance":["..."]}]`\n'
        )
    return (
        f"# Worker Task: {task['id']}\n\n"
        f"## Titel\n{task['title']}\n\n"
        f"## Beschreibung\n{task['description']}\n\n"
        f"## Abnahmekriterien\n{acceptance}\n\n"
        "## Erwartetes Ergebnis\n"
        "- Implementiere die Aufgabe direkt im aktuellen Repository.\n"
        "- Fasse geaenderte Dateien zusammen.\n"
        "- Nenne ausgefuehrte Tests und Ergebnisse.\n"
        "- Falls blockiert: dokumentiere den Blocker klar.\n"
        f"{optional_followup}"
    )


def run_git_status() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return f"git status failed: {result.stderr.strip()}"
    except FileNotFoundError:
        return "git not available"


def worker_timeout_seconds() -> int:
    raw = os.environ.get("WORKER_TIMEOUT_SECONDS", str(DEFAULT_WORKER_TIMEOUT_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WORKER_TIMEOUT_SECONDS
    if value < 0:
        return DEFAULT_WORKER_TIMEOUT_SECONDS
    return value


def followup_policy() -> str:
    raw = os.environ.get("ORCH_FOLLOWUP_POLICY", DEFAULT_FOLLOWUP_POLICY).strip().lower()
    aliases = {
        "0": "none",
        "off": "none",
        "false": "none",
        "disable": "none",
        "disabled": "none",
        "1": "all",
        "on": "all",
        "true": "all",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in FOLLOWUP_POLICY_VALUES:
        return DEFAULT_FOLLOWUP_POLICY
    return normalized


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def ensure_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def detect_worker_failures(stdout_text: str, stderr_text: str) -> list[str]:
    combined = f"{stdout_text or ''}\n{stderr_text or ''}"
    diagnostic_lines: list[str] = []
    reasons: list[str] = []
    explicit_error_hints = (
        "stream disconnected before completion",
        "failed to shutdown rollout recorder",
        "authentication failed",
        "unauthorized",
        "does not exist or you do not have access to it",
    )

    for line in combined.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if (
            stripped.startswith("ERROR:")
            or stripped.startswith("Reconnecting...")
            or " stream error:" in lowered
            or lowered.startswith("stream error:")
            or TIMESTAMPED_ERROR_RE.match(stripped)
        ):
            diagnostic_lines.append(stripped)

    lower = "\n".join(diagnostic_lines).lower()
    for needle, message in FATAL_WORKER_PATTERNS.items():
        if needle in lower:
            reasons.append(message)

    for stripped in diagnostic_lines:
        lowered = stripped.lower()
        if stripped.startswith("ERROR:") and any(hint in lowered for hint in explicit_error_hints):
            reasons.append(f"Worker meldet Fehler: {stripped[:180]}")
            break

    return dedupe(reasons)


def write_run_artifacts(
    run_dir: Path,
    task_id: str,
    command: str,
    result: subprocess.CompletedProcess[str],
    started: str,
    finished: str,
    effective_success: bool,
    failure_reasons: list[str],
) -> None:
    stdout_text = result.stdout or ""
    stderr_text = result.stderr or ""
    (run_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (run_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "command": command,
                "returncode": result.returncode,
                "effective_success": effective_success,
                "failure_reasons": failure_reasons,
                "started_at": started,
                "finished_at": finished,
                "git_status_after": run_git_status(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def resolve_worker_template_or_placeholder(prompt_file: Path) -> tuple[str, bool]:
    worker_template = os.environ.get("WORKER_CMD")
    if worker_template:
        return resolve_worker_command(worker_template, prompt_file), True
    return "<set WORKER_CMD to enable real dispatch>", False


def dispatch_task(queue: dict, task: dict, dry_run: bool) -> dict:
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / task["id"] / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = run_dir / "worker_prompt.md"
    prompt_file.write_text(build_worker_prompt(task, run_dir=run_dir), encoding="utf-8")

    command, has_worker_cmd = resolve_worker_template_or_placeholder(prompt_file)
    if dry_run:
        return {
            "task_id": task["id"],
            "run_dir": run_dir,
            "dry_run": True,
            "command": command,
            "effective_success": True,
            "worker_cmd_found": has_worker_cmd,
            "returncode": 0,
            "failure_reasons": [],
        }

    if not has_worker_cmd:
        return {
            "task_id": task["id"],
            "run_dir": run_dir,
            "dry_run": False,
            "command": command,
            "effective_success": False,
            "worker_cmd_found": False,
            "returncode": 2,
            "failure_reasons": ["WORKER_CMD ist nicht gesetzt."],
        }

    previous_status = task["status"]
    task["status"] = "in_progress"
    task["updated_at"] = now_iso()
    save_queue(queue)

    started = now_iso()
    timeout_seconds = worker_timeout_seconds()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
        )
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=ensure_text(exc.stdout),
            stderr=ensure_text(exc.stderr),
        )
    finished = now_iso()

    failure_reasons = detect_worker_failures(result.stdout or "", result.stderr or "")
    if result.returncode == 124 and timeout_seconds > 0:
        failure_reasons.append(f"Worker-Timeout nach {timeout_seconds}s erreicht.")
    failure_reasons = dedupe(failure_reasons)
    effective_success = result.returncode == 0 and not failure_reasons
    write_run_artifacts(
        run_dir=run_dir,
        task_id=task["id"],
        command=command,
        result=result,
        started=started,
        finished=finished,
        effective_success=effective_success,
        failure_reasons=failure_reasons,
    )

    task["attempts"] += 1
    task["last_run"] = str(run_dir)
    task["updated_at"] = now_iso()
    task["status"] = "submitted" if effective_success else "rework"
    event_type = "worker_submitted" if effective_success else "worker_failed"

    add_history(
        queue,
        {
            "type": event_type,
            "task_id": task["id"],
            "returncode": result.returncode,
            "effective_success": effective_success,
            "failure_reasons": failure_reasons,
            "previous_status": previous_status,
            "run_dir": str(run_dir),
        },
    )
    save_queue(queue)
    return {
        "task_id": task["id"],
        "run_dir": run_dir,
        "dry_run": False,
        "command": command,
        "effective_success": effective_success,
        "worker_cmd_found": True,
        "returncode": result.returncode,
        "failure_reasons": failure_reasons,
    }


def pick_dispatch_task(tasks: list[dict], task_id: str | None, exclude_ids: set[str] | None = None) -> dict | None:
    excluded = exclude_ids or set()
    if task_id:
        task = find_task(tasks, task_id)
        if task and task["id"] not in excluded:
            return task
        return None
    for task in tasks:
        if task["status"] in OPEN_STATUSES and task["id"] not in excluded:
            return task
    return None


def resolve_worker_command(template: str, prompt_file: Path) -> str:
    quoted_prompt = shlex.quote(str(prompt_file))
    if "{prompt_file}" in template:
        return template.format(prompt_file=quoted_prompt)
    return f"{template} {quoted_prompt}"


def cmd_dispatch(args: argparse.Namespace) -> int:
    queue = load_queue()
    task = pick_dispatch_task(queue["tasks"], args.task_id)
    if task is None:
        print("No dispatchable task found.")
        return 1

    outcome = dispatch_task(queue, task, dry_run=args.dry_run)
    run_dir = outcome["run_dir"]
    if args.dry_run:
        print(f"Dry run for {task['id']}")
        print(f"Command: {outcome['command']}")
        print(f"Prompt:  {run_dir / 'worker_prompt.md'}")
        return 0

    if not outcome["worker_cmd_found"]:
        print("WORKER_CMD is not set. Dispatch aborted.")
        print(f"Prompt prepared at: {run_dir / 'worker_prompt.md'}")
        return 2

    print(f"Dispatched {task['id']} with return code {outcome['returncode']}")
    print(f"Run artifacts: {run_dir}")
    if outcome["failure_reasons"]:
        print("Failure reasons:")
        for reason in outcome["failure_reasons"]:
            print(f"- {reason}")
    return 0 if outcome["effective_success"] else (outcome["returncode"] or 1)


def extract_required_paths(acceptance: list[str]) -> list[str]:
    paths: set[str] = set()
    for criterion in acceptance:
        for raw in PATH_TOKEN_RE.findall(criterion):
            token = raw.strip("`'\"()[]{}").rstrip(".,:;!?")
            if not token:
                continue
            if "/" in token:
                first_part = token.split("/", 1)[0]
                looks_like_path = (
                    "." in token
                    or token.startswith("./")
                    or token.startswith("../")
                    or first_part in COMMON_PATH_PREFIXES
                )
                if looks_like_path:
                    paths.add(token)
                continue
            if token in {"README", "README.md"}:
                paths.add("README")
                continue
            if "." in token and not token.startswith("--"):
                paths.add(token)
    return sorted(paths)


def missing_required_paths(task: dict) -> list[str]:
    missing: list[str] = []
    run_dir_raw = task.get("last_run")
    run_dir = Path(run_dir_raw) if run_dir_raw else None
    for required in extract_required_paths(task.get("acceptance", [])):
        if required == "README":
            if not Path("README").exists() and not Path("README.md").exists():
                missing.append("README (oder README.md)")
            continue
        if Path(required).exists():
            continue
        if run_dir is not None and (run_dir / required).exists():
            continue
        if required == "meta.json" and run_dir is not None and (run_dir / "meta.json").exists():
            continue
        if required == "stdout.log" and run_dir is not None and (run_dir / "stdout.log").exists():
            continue
        if required == "stderr.log" and run_dir is not None and (run_dir / "stderr.log").exists():
            continue
        if required == "worker_prompt.md" and run_dir is not None and (run_dir / "worker_prompt.md").exists():
            continue
        if required == "followup_tasks.json" and run_dir is not None and (run_dir / "followup_tasks.json").exists():
            continue
        if required == "next_tasks.json" and run_dir is not None and (run_dir / "next_tasks.json").exists():
            continue
        if required.startswith("./") and Path(required[2:]).exists():
            continue
        if required.startswith("./") and run_dir is not None and (run_dir / required[2:]).exists():
            continue
        # Accept bare filenames that live in subdirectories of the workspace.
        if "/" not in required and any(path.is_file() for path in Path(".").glob(f"**/{required}")):
            continue
        missing.append(required)
    return missing


def load_run_meta(run_dir: Path) -> dict:
    meta_file = run_dir / "meta.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def auto_review_decision(task: dict) -> tuple[str, str]:
    reasons: list[str] = []
    run_dir_raw = task.get("last_run")
    if not run_dir_raw:
        reasons.append("Kein Run-Artefakt vorhanden.")
        return "rework", "; ".join(reasons)

    run_dir = Path(run_dir_raw)
    meta = load_run_meta(run_dir)
    stdout_text = (run_dir / "stdout.log").read_text(encoding="utf-8") if (run_dir / "stdout.log").exists() else ""
    stderr_text = (run_dir / "stderr.log").read_text(encoding="utf-8") if (run_dir / "stderr.log").exists() else ""
    detected_runtime_failures = detect_worker_failures(stdout_text, stderr_text)

    if not meta:
        reasons.append("Run-Metadaten fehlen oder sind unlesbar.")
    else:
        returncode = meta.get("returncode")
        if returncode not in (0, None):
            reasons.append(f"Worker returncode ist {returncode}.")
            reasons.extend(meta.get("failure_reasons", []))
        elif meta.get("effective_success") is False and detected_runtime_failures:
            # Backward-compatible: keep meta-reasons only if log-level diagnostics still confirm them.
            reasons.extend(meta.get("failure_reasons", []))

    reasons.extend(detected_runtime_failures)

    missing = missing_required_paths(task)
    if missing:
        reasons.append("Fehlende geforderte Dateien: " + ", ".join(missing))

    reasons = dedupe(reasons)
    if reasons:
        return "rework", "; ".join(reasons)
    return "approve", "Auto-Review erfolgreich (keine Blocker erkannt)."


def apply_review_decision(queue: dict, task: dict, decision: str, note: str) -> None:
    note_entry = {"at": now_iso(), "decision": decision, "note": note}
    task["review_notes"].append(note_entry)
    task["updated_at"] = now_iso()
    task["status"] = "approved" if decision == "approve" else "rework"

    add_history(
        queue,
        {
            "type": "reviewed",
            "task_id": task["id"],
            "decision": decision,
            "note": note,
        },
    )


def normalize_followup_spec(raw: dict) -> dict | None:
    title = str(raw.get("title", "")).strip()
    description = str(raw.get("description", "")).strip()
    if not title or not description:
        return None

    acceptance_raw = raw.get("acceptance", [])
    if isinstance(acceptance_raw, str):
        acceptance = [acceptance_raw.strip()] if acceptance_raw.strip() else []
    elif isinstance(acceptance_raw, list):
        acceptance = [str(x).strip() for x in acceptance_raw if str(x).strip()]
    else:
        acceptance = []

    return {"title": title, "description": description, "acceptance": acceptance}


def is_bugfix_followup(spec: dict) -> bool:
    haystack = f"{spec.get('title', '')} {spec.get('description', '')}".lower()
    return any(keyword in haystack for keyword in BUGFIX_FOLLOWUP_KEYWORDS)


def filter_followup_specs(specs: list[dict], policy: str) -> list[dict]:
    if policy == "none":
        return []
    if policy == "bugfix_only":
        return [spec for spec in specs if is_bugfix_followup(spec)]
    return specs


def load_followup_tasks(run_dir: Path) -> list[dict]:
    candidates = [run_dir / "followup_tasks.json", run_dir / "next_tasks.json"]
    for file_path in candidates:
        if not file_path.exists():
            continue
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, list):
            continue
        normalized: list[dict] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            spec = normalize_followup_spec(item)
            if spec:
                normalized.append(spec)
        return normalized
    return []


def add_task_spec(queue: dict, spec: dict, source_task_id: str) -> str:
    task = {
        "id": next_task_id(queue["tasks"]),
        "title": spec["title"],
        "description": spec["description"],
        "acceptance": spec["acceptance"],
        "status": "ready",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "attempts": 0,
        "last_run": None,
        "review_notes": [],
    }
    queue["tasks"].append(task)
    add_history(
        queue,
        {
            "type": "task_added_from_followup",
            "source_task_id": source_task_id,
            "task_id": task["id"],
            "title": task["title"],
        },
    )
    return task["id"]


def maybe_add_followup_tasks(queue: dict, task: dict) -> list[str]:
    run_dir_raw = task.get("last_run")
    if not run_dir_raw:
        return []
    run_dir = Path(run_dir_raw)
    specs = load_followup_tasks(run_dir)
    policy = followup_policy()
    specs = filter_followup_specs(specs, policy)
    added_ids: list[str] = []
    for spec in specs:
        added_ids.append(add_task_spec(queue, spec, source_task_id=task["id"]))
    return added_ids


def cmd_review(args: argparse.Namespace) -> int:
    queue = load_queue()
    task = find_task(queue["tasks"], args.task_id)
    if task is None:
        print(f"Task not found: {args.task_id}")
        return 1
    apply_review_decision(queue, task, args.decision, args.notes or "")
    save_queue(queue)
    print(f"{task['id']} set to {task['status']}")
    return 0


def cmd_autopilot(args: argparse.Namespace) -> int:
    processed = 0
    selected_task_id = args.task_id
    visited_ids: set[str] = set()

    while True:
        queue = load_queue()
        task = pick_dispatch_task(queue["tasks"], selected_task_id, exclude_ids=visited_ids)
        if task is None:
            if processed == 0:
                print("No dispatchable task found.")
                return 1
            print("Autopilot finished: no further open tasks.")
            return 0

        outcome = dispatch_task(queue, task, dry_run=args.dry_run)
        if args.dry_run:
            print(f"Dry run for {task['id']}")
            print(f"Command: {outcome['command']}")
            print(f"Prompt:  {outcome['run_dir'] / 'worker_prompt.md'}")
            return 0
        if not outcome["worker_cmd_found"]:
            print("WORKER_CMD is not set. Autopilot aborted.")
            print(f"Prompt prepared at: {outcome['run_dir'] / 'worker_prompt.md'}")
            return 2

        queue = load_queue()
        task = find_task(queue["tasks"], task["id"])
        if task is None:
            print("Autopilot aborted: task vanished from queue.")
            return 1

        decision, note = auto_review_decision(task)
        apply_review_decision(queue, task, decision, note)
        added_ids: list[str] = []
        if decision == "approve":
            added_ids = maybe_add_followup_tasks(queue, task)
        save_queue(queue)

        print(f"Autopilot review: {task['id']} -> {task['status']}")
        if note:
            print(f"Review note: {note}")
        if added_ids:
            print(f"Follow-up tasks added: {', '.join(added_ids)}")

        processed += 1
        visited_ids.add(task["id"])
        if args.max_tasks > 0 and processed >= args.max_tasks:
            print(f"Autopilot reached max tasks ({args.max_tasks}).")
            return 0
        if decision == "rework" and not args.continue_on_rework:
            print("Autopilot stopped because task needs rework.")
            return 1
        selected_task_id = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Planner/Worker orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="initialize folder layout")
    init_p.set_defaults(func=cmd_init)

    task_p = sub.add_parser("task", help="task operations")
    task_sub = task_p.add_subparsers(dest="task_command", required=True)

    add_p = task_sub.add_parser("add", help="add task")
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--description", required=True)
    add_p.add_argument(
        "--acceptance",
        action="append",
        help="acceptance criterion (repeatable)",
    )
    add_p.set_defaults(func=cmd_task_add)

    list_p = task_sub.add_parser("list", help="list tasks")
    list_p.add_argument("--status")
    list_p.set_defaults(func=cmd_task_list)

    status_p = sub.add_parser("status", help="show queue summary and resume hints")
    status_p.set_defaults(func=cmd_status)

    dispatch_p = sub.add_parser("dispatch", help="send task to worker")
    dispatch_p.add_argument("--task-id", help="explicit task id")
    dispatch_p.add_argument("--dry-run", action="store_true")
    dispatch_p.set_defaults(func=cmd_dispatch)

    autopilot_p = sub.add_parser("autopilot", help="dispatch + auto-review loop")
    autopilot_p.add_argument("--task-id", help="start with explicit task id")
    autopilot_p.add_argument(
        "--max-tasks",
        type=int,
        default=0,
        help="stop after N processed tasks (0 = until queue is blocked/empty)",
    )
    autopilot_p.add_argument(
        "--continue-on-rework",
        action="store_true",
        help="continue with next task even if current one is set to rework",
    )
    autopilot_p.add_argument("--dry-run", action="store_true")
    autopilot_p.set_defaults(func=cmd_autopilot)

    review_p = sub.add_parser("review", help="review worker result")
    review_p.add_argument("--task-id", required=True)
    review_p.add_argument("--decision", choices=["approve", "rework"], required=True)
    review_p.add_argument("--notes")
    review_p.set_defaults(func=cmd_review)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
