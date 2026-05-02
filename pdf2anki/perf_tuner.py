"""
perf_tuner.py — Per-model OCR concurrency tuner.

Records each OCR run's outcome (model, concurrency level, pages newly
completed, transient errors, paused-y/n) as one append-only NDJSON line
under ~/.pdf2anki/perf_log.ndjson. On the next run, reads recent lines
for the same model_id and recommends a concurrency level using a simple
AIMD-style policy:

  * Run paused             -> recommend last_conc // 2 (hard demote).
  * Run had errors         -> recommend last_conc - 1 (soft demote).
  * 3+ clean runs at level -> recommend last_conc + 1 (probe higher).
  * Otherwise              -> stick with last_conc.

Cold start (no observations yet) uses a per-provider seed table.

Resume compatibility: callers must pass the *newly completed* page count
(not total), so resumed-from-state pages do not count as observations.

Tuner failures must never break OCR — every public function is wrapped
in try/except and falls back to the provider seed.

Disable entirely with env var PDF2ANKI_DISABLE_TUNER=1.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Cold-start seeds by OpenRouter model_id prefix. Resilience-first: small
# values that almost any account can handle. The tuner ramps up from here.
COLD_START_SEEDS: Dict[str, int] = {
    "google/": 12,
    "openai/": 8,
    "anthropic/": 6,
    "deepseek/": 8,
    "mistralai/": 8,
    "meta-llama/": 8,
}
_DEFAULT_COLD_START = 4

# Newest N lines considered when computing a recommendation.
RECENT_WINDOW = 30

# Lower bound: a run with fewer than this many *new* pages produces no
# observation. Resumed runs that finish quickly otherwise dominate the log
# with weak signal.
MIN_PAGES_FOR_OBSERVATION = 5

# Upper bound on recommended concurrency. The pic2text API pool caps at 20
# anyway; staying below avoids starvation when judge/repeat fan-out is on.
MAX_RECOMMENDED_CONCURRENCY = 16

# How many consecutive clean runs at the same level before probing higher.
CLEAN_RUNS_BEFORE_PROBE = 3


_write_lock = threading.Lock()


def is_disabled() -> bool:
    return os.environ.get("PDF2ANKI_DISABLE_TUNER", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _profile_path() -> Path:
    home = Path.home()
    d = home / ".pdf2anki"
    d.mkdir(parents=True, exist_ok=True)
    return d / "perf_log.ndjson"


def _seed_for(model_id: str) -> int:
    for prefix, val in COLD_START_SEEDS.items():
        if model_id.startswith(prefix):
            return val
    return _DEFAULT_COLD_START


def _read_recent_observations(model_id: str) -> List[Dict[str, Any]]:
    path = _profile_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    matches: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate single-line corruption
        if obs.get("model") == model_id:
            matches.append(obs)
    return matches[-RECENT_WINDOW:]


def get_recommended_concurrency(model_id: str) -> int:
    """Return concurrency level to use for the next run with this model."""
    if is_disabled():
        return _seed_for(model_id)
    try:
        recent = _read_recent_observations(model_id)
        if not recent:
            return _seed_for(model_id)
        last = recent[-1]
        last_conc = int(last.get("concurrency", _seed_for(model_id)))
        if last.get("paused", False):
            return max(1, last_conc // 2)
        if int(last.get("errors", 0)) > 0:
            return max(1, last_conc - 1)
        # Clean last run. Probe higher only if recent history at this level
        # has been clean too.
        clean_at_level = 0
        for obs in reversed(recent):
            if int(obs.get("concurrency", -1)) != last_conc:
                break
            if obs.get("paused", False) or int(obs.get("errors", 0)) > 0:
                break
            clean_at_level += 1
            if clean_at_level >= CLEAN_RUNS_BEFORE_PROBE:
                break
        if clean_at_level >= CLEAN_RUNS_BEFORE_PROBE:
            return min(MAX_RECOMMENDED_CONCURRENCY, last_conc + 1)
        return last_conc
    except Exception:
        return _seed_for(model_id)


def record_observation(
    model_id: str,
    concurrency: int,
    pages_completed: int,
    errors: int,
    paused: bool,
) -> None:
    """Append one NDJSON line. Silent on any failure."""
    if is_disabled():
        return
    if pages_completed < MIN_PAGES_FOR_OBSERVATION and not paused:
        return  # too little signal
    record = {
        "ts": datetime.now().isoformat(),
        "model": model_id,
        "concurrency": int(concurrency),
        "pages_completed": int(pages_completed),
        "errors": int(errors),
        "paused": bool(paused),
    }
    try:
        path = _profile_path()
        with _write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def resolve_concurrency(model_id: Optional[str], explicit: Optional[int]) -> int:
    """Single chokepoint for callers.

    explicit=None -> ask the tuner (or seed if disabled / no model_id).
    explicit=int  -> honor it verbatim, never persist anything from this run.
    """
    if explicit is not None:
        return max(1, int(explicit))
    if not model_id:
        return _DEFAULT_COLD_START
    return get_recommended_concurrency(model_id)
