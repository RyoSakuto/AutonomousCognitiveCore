import json
import time
import pathlib
import sys

# damit src/ importierbar ist wie in run.py
sys.path.append(str(pathlib.Path(__file__).resolve().parent / "src"))

from core.api import boot, add_experience, run_task

BASE = pathlib.Path(__file__).resolve().parent
INBOX = BASE / "inbox"
OUTBOX = BASE / "outbox"
ARCHIVE = BASE / "archive"

def ensure_dirs():
    INBOX.mkdir(exist_ok=True)
    OUTBOX.mkdir(exist_ok=True)
    ARCHIVE.mkdir(exist_ok=True)

def load_event(path: pathlib.Path) -> dict:
    # Event kann JSON sein oder reiner Text
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return {"text": path.read_text(encoding="utf-8").strip(), "source": "inbox"}

def write_out(event_id: str, payload: dict):
    out = OUTBOX / f"{event_id}.response.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def main(poll_seconds: float = 0.5):
    ensure_dirs()
    boot()

    print(f"👂 NIMCF agent listening on: {INBOX}")
    while True:
        for path in sorted(INBOX.glob("*")):
            if path.is_dir():
                continue

            event_id = path.stem
            try:
                evt = load_event(path)
                text = (evt.get("text") or "").strip()
                if not text:
                    path.rename(ARCHIVE / path.name)
                    continue

                # 1) Wahrnehmung + Gedächtnis
                add_experience({
                    "text": text,
                    "source": evt.get("source", "inbox"),
                    "metadata": evt.get("metadata", {}),
                    "context": evt.get("context", {}),
                    "affect": evt.get("affect")  # optional
                })

                # 2) Entscheidung: reagieren oder nicht?
                # Minimal: immer eine Reflexion/Planung probieren
                # Später: Gate (z.B. nur reagieren wenn "to_nimcf": true oder Score > X)
                result = run_task(
                    goal=evt.get("goal", "reflect"),
                    payload=evt.get("payload", {"text": text}),
                    capabilities=evt.get("capabilities", ["reflect", "memory-search"])
                )

                # 3) Handlung: Antwort raus
                write_out(event_id, {
                    "input": text,
                    "result": result
                })

            except Exception as e:
                write_out(event_id, {"error": str(e)})
            finally:
                # Event archivieren (damit es nur einmal verarbeitet wird)
                try:
                    path.rename(ARCHIVE / path.name)
                except Exception:
                    pass

        time.sleep(poll_seconds)

if __name__ == "__main__":
    main()

