"""
pipeline_trace.py — Structured execution trace for pdf2anki lazy mode.

Writes a pipeline_trace.json to the project directory. Each run of
`pdf2anki .` appends one run object containing per-phase timing,
LLM cost/token metadata, card counts, and a summary.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _extract_llm_metadata(responses: list[dict]) -> list[dict]:
    """Extract model, cost, and token counts from raw OpenRouter responses."""
    calls: list[dict] = []
    for resp in responses:
        if "error" in resp:
            calls.append({"error": resp["error"]})
            continue
        usage = resp.get("usage", {})
        details = usage.get("prompt_tokens_details", {})
        calls.append({
            "model": resp.get("model", "unknown"),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "cached_tokens": details.get("cached_tokens", 0),
            "cost": usage.get("cost", 0.0),
        })
    return calls


class PipelineTrace:
    """Accumulates structured trace data for one pipeline run."""

    def __init__(self, trace_path: Path):
        self._trace_path = Path(trace_path)
        self._runs: list[dict] = self._load()
        self._current_run: dict | None = None
        self._current_run_index: int | None = None
        self._phase_starts: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def begin_run(self) -> None:
        ts = _now()
        self._current_run = {
            "run_id": f"{ts}_{uuid.uuid4().hex[:8]}",
            "started_at": ts,
            "finished_at": None,
            "status": "running",
            "error": None,
            "phases": {},
            "summary": {},
        }
        self._runs.append(self._current_run)
        self._current_run_index = len(self._runs) - 1
        self._flush()

    def begin_phase(self, phase: str) -> None:
        self._phase_starts[phase] = _now()

    def end_phase(
        self,
        phase: str,
        status: str,
        metadata: dict[str, Any] | None = None,
        llm_responses: list[dict] | None = None,
    ) -> None:
        if self._current_run is None:
            return
        phase_data: dict[str, Any] = {
            "started_at": self._phase_starts.pop(phase, None),
            "finished_at": _now(),
            "status": status,
        }
        if metadata:
            phase_data.update(metadata)
        if llm_responses:
            phase_data["llm_calls"] = _extract_llm_metadata(llm_responses)
        self._current_run["phases"][phase] = phase_data
        self._flush()

    def end_run(self, status: str = "ok", error: str | None = None) -> None:
        if self._current_run is None:
            return
        self._current_run["finished_at"] = _now()
        self._current_run["status"] = status
        self._current_run["error"] = error
        self._current_run["summary"] = self._compute_summary()
        self._flush()
        self._current_run = None
        self._current_run_index = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_summary(self) -> dict:
        phases = self._current_run.get("phases", {}) if self._current_run else {}
        total_cost = 0.0
        total_llm_calls = 0
        errors: list[str] = []

        for phase_name, phase_data in phases.items():
            for call in phase_data.get("llm_calls", []):
                if "error" in call:
                    errors.append(f"{phase_name}: {call['error']}")
                else:
                    total_cost += call.get("cost", 0.0)
                    total_llm_calls += 1
            if phase_data.get("error"):
                errors.append(f"{phase_name}: {phase_data['error']}")

        started = self._current_run.get("started_at", "")
        finished = self._current_run.get("finished_at", "")
        total_time = None
        if started and finished:
            try:
                t0 = datetime.fromisoformat(started)
                t1 = datetime.fromisoformat(finished)
                total_time = round((t1 - t0).total_seconds(), 3)
            except ValueError:
                pass

        # Card stats from phases
        cards_generated = phases.get("ingest", {}).get("cards_generated", 0)
        cards_added = phases.get("integrate", {}).get("cards_added", 0)
        apkg_files = len(phases.get("export", {}).get("files_generated", []))

        return {
            "total_time_seconds": total_time,
            "total_cost": round(total_cost, 8),
            "total_llm_calls": total_llm_calls,
            "total_cards_generated": cards_generated,
            "total_cards_added": cards_added,
            "total_apkg_files": apkg_files,
            "errors": errors,
        }

    def _load(self) -> list[dict]:
        if not self._trace_path.exists():
            return []
        try:
            data = json.loads(self._trace_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            # Corrupt file — rename and start fresh
            bak = self._trace_path.with_suffix(".json.bak")
            try:
                self._trace_path.rename(bak)
            except OSError:
                pass
        return []

    def _flush(self) -> None:
        tmp = self._trace_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self._runs, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._trace_path)
        except OSError:
            pass
