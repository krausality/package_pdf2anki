"""
forensic_logger.py — Append-only JSONL forensic log for pdf2anki pipeline runs.

Captures every LLM request/response, tool call, content sample, and parse decision
at maximum verbosity. Written to log_archive/forensic/<run_id>.jsonl.

Module-level singleton API (matches _session_responses pattern in llm_helper.py):
    init_forensic_log(log_dir, run_id)  — open log file for this run
    log_event(event, data)              — append one JSONL line (no-op if not initialized)
    set_phase(phase)                    — set current phase context for subsequent events
    get_forensic_log_path()             — return current log file path
    close_forensic_log()                — flush and close
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_log_file = None
_log_path: Path | None = None
_current_phase: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_forensic_log(log_dir: Path, run_id: str) -> None:
    """Create log_archive/forensic/<run_id>.jsonl and set as active log."""
    global _log_file, _log_path, _current_phase
    close_forensic_log()

    forensic_dir = Path(log_dir) / "forensic"
    forensic_dir.mkdir(parents=True, exist_ok=True)

    safe_id = run_id.replace(":", "-")
    _log_path = forensic_dir / f"{safe_id}.jsonl"
    _log_file = open(_log_path, "a", encoding="utf-8")
    _current_phase = None


def set_phase(phase: str | None) -> None:
    """Set the current pipeline phase for subsequent log_event calls."""
    global _current_phase
    _current_phase = phase


def log_event(event: str, data: dict[str, Any] | None = None) -> None:
    """Append a timestamped event to the forensic log. No-op if not initialized."""
    if _log_file is None:
        return
    entry = {
        "ts": _now(),
        "phase": _current_phase,
        "event": event,
    }
    if data:
        entry["data"] = data
    try:
        _log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _log_file.flush()
    except (OSError, ValueError):
        pass


def get_forensic_log_path() -> Path | None:
    """Return the path of the current forensic log file, or None."""
    return _log_path


def close_forensic_log() -> None:
    """Flush and close the forensic log, reset singleton state."""
    global _log_file, _log_path, _current_phase
    if _log_file is not None:
        try:
            _log_file.flush()
            _log_file.close()
        except OSError:
            pass
    _log_file = None
    _log_path = None
    _current_phase = None
