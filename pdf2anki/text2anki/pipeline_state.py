"""
Pipeline state inference for pdf2anki.

Determines where each PDF+TXT pair is in the pipeline (OCR, ingest, export)
by reading existing file signals — no LLM, no I/O side effects beyond reads.

OCR completion signal (race-condition-free, no changes to pic2text.py needed):
  - ocr_state.json absent + .txt exists  →  done (state was archived after completion)
  - ocr_state.json present + run_status=completed  →  done (tiny window before archival)
  - ocr_state.json present + run_status=paused     →  paused
  - ocr_state.json present + run_status=running    →  running
  - .txt absent                                    →  pending
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Literal, NamedTuple

# Directories to skip entirely during recursive scan
_IGNORED_DIRS = {"pdf2pic", "log_archive"}

OcrStatus = Literal["done", "running", "paused", "pending"]
IngestStatus = Literal["done", "pending"]
ExportStatus = Literal["done", "pending"]


class PipelineState(NamedTuple):
    ocr: OcrStatus
    ingest: IngestStatus
    export: ExportStatus


def infer_ocr_status(txt_path: Path) -> OcrStatus:
    """Return OCR status for a given .txt output path."""
    state_path = txt_path.with_name(f"{txt_path.name}.ocr_state.json")

    if not txt_path.exists():
        return "pending"

    if not state_path.exists():
        # State file was archived → OCR completed cleanly
        return "done"

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        run_status = state.get("run_status", "running")
    except (json.JSONDecodeError, OSError):
        # Unreadable state file while .txt exists → assume actively running
        return "running"

    if run_status == "completed":
        return "done"
    if run_status == "paused":
        return "paused"
    return "running"


def infer_project_state(project_dir: Path) -> tuple[IngestStatus, ExportStatus]:
    """
    Return (ingest_status, export_status) for a project directory.

    ingest=done  iff  card_database.json exists and is non-trivially populated.
    export=done  iff  at least one .apkg file exists in the project directory.
    """
    db_path = project_dir / "card_database.json"
    ingest: IngestStatus = "pending"
    if db_path.exists():
        try:
            data = json.loads(db_path.read_text(encoding="utf-8"))
            # card_database.json is a flat array of card objects
            if isinstance(data, list) and len(data) > 0:
                ingest = "done"
            elif isinstance(data, dict) and data.get("cards"):
                ingest = "done"
        except (json.JSONDecodeError, OSError):
            pass

    export: ExportStatus = "done" if any(project_dir.glob("*.apkg")) else "pending"
    return ingest, export


def scan_directory(base_dir: Path) -> Dict[str, PipelineState]:
    """
    Recursively scan base_dir for PDF files and return a mapping of
    relative PDF path (str) → PipelineState.

    Directories named 'pdf2pic' or 'log_archive' are skipped entirely.
    Only .pdf and .txt files are considered as signals.
    """
    base_dir = base_dir.resolve()
    ingest_status, export_status = infer_project_state(base_dir)

    results: Dict[str, PipelineState] = {}

    for pdf_path in _walk_pdfs(base_dir):
        # Expected OCR output: same stem, .txt extension, same directory
        txt_path = pdf_path.with_suffix(".txt")
        ocr = infer_ocr_status(txt_path)
        rel = str(pdf_path.relative_to(base_dir))
        results[rel] = PipelineState(ocr=ocr, ingest=ingest_status, export=export_status)

    return results


def _walk_pdfs(base_dir: Path):
    """Yield all .pdf paths under base_dir, skipping ignored directories."""
    for item in base_dir.iterdir():
        if item.is_dir():
            if item.name in _IGNORED_DIRS:
                continue
            yield from _walk_pdfs(item)
        elif item.is_file() and item.suffix.lower() == ".pdf":
            yield item
