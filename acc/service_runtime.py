from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Callable

import fcntl


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StructuredLogger:
    def __init__(self, enabled: bool, path: str) -> None:
        self.enabled = bool(enabled)
        self.path = Path(path)
        self._lock = Lock()
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields: object) -> None:
        if not self.enabled:
            return
        payload = {"ts": _now_iso(), "event": event, **fields}
        line = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class SingleInstanceLock:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"daemon lock already held: {self.path}") from exc
        self._handle.seek(0)
        self._handle.truncate()
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": _now_iso(),
        }
        self._handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self._handle.flush()

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


@dataclass
class HealthServer:
    host: str
    port: int
    provider: Callable[[], dict]
    _server: ThreadingHTTPServer | None = None
    _thread: Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        provider = self.provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path not in ("/health", "/healthz"):
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok":false,"error":"not_found"}')
                    return
                payload = provider()
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
