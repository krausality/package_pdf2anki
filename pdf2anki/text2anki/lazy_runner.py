"""
lazy_runner.py — Entry point for `pdf2anki .` lazy mode.

Scans the working directory, discovers/creates project.json via LLM or wizard,
infers pipeline state, generates an ordered execution plan, and runs pending steps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .pipeline_state import scan_directory, infer_ocr_status
from .project_config import ProjectConfig
from .console_utils import safe_print
from .llm_discovery import LLMDiscoveryLoop
from .guided_wizard import run_guided_wizard
from .workflow_manager import WorkflowManager

_DEFAULT_OCR_MODEL = "google/gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_lazy_mode(
    base_dir: Path,
    turns: int = 5,
    no_llm: bool = False,
    reconfig: bool = False,
    ocr_model: Optional[str] = None,
) -> None:
    """
    Full lazy-mode pipeline for `pdf2anki .`.

    Args:
        base_dir:  Directory to scan and operate in.
        turns:     Max LLM discovery turns (ignored when no_llm=True).
        no_llm:    If True, use the guided CLI wizard instead of LLM discovery.
        reconfig:  If True, re-run discovery even if project.json already exists.
        ocr_model: OCR model to use for pending PDFs. Defaults to gemini-2.5-flash.
    """
    base_dir = base_dir.resolve()
    ocr_model = ocr_model or _DEFAULT_OCR_MODEL

    safe_print(f"\n=== pdf2anki . (lazy mode) — {base_dir} ===\n")

    # ── Step 1: Ensure project.json ──────────────────────────────────────────
    project_json_path = base_dir / "project.json"
    config = _ensure_project_config(
        base_dir=base_dir,
        project_json_path=project_json_path,
        turns=turns,
        no_llm=no_llm,
        reconfig=reconfig,
    )
    if config is None:
        safe_print("Aborted: project.json could not be created.", "ERROR")
        return

    # ── Step 2: Pipeline state + plan ────────────────────────────────────────
    state_map = scan_directory(base_dir)
    _print_plan(state_map)

    # ── Step 3: Execute pending steps ────────────────────────────────────────
    manager = WorkflowManager(project_dir=str(base_dir))

    # OCR: process all PDFs that haven't been OCR'd yet
    ocr_done_txts = _run_pending_ocr(base_dir, state_map, ocr_model)

    # Ingest: collect all OCR-complete .txt files
    state_map = scan_directory(base_dir)  # re-scan after OCR
    txt_files = _collect_ocr_txts(base_dir, state_map)

    if txt_files:
        safe_print(f"\n--- Ingest: {len(txt_files)} Datei(en) ---")
        manager.run_ingest_workflow(txt_files)

        safe_print("\n--- Integrate ---")
        manager.run_integrate_workflow()

    # Export: always attempt if we have a populated database
    state_map = scan_directory(base_dir)
    if any(s.ingest == "done" for s in state_map.values()) or _db_has_cards(base_dir):
        safe_print("\n--- Export ---")
        manager.run_export_workflow()

    safe_print("\n=== pdf2anki . abgeschlossen ===\n")


# ---------------------------------------------------------------------------
# Project config setup
# ---------------------------------------------------------------------------

def _ensure_project_config(
    base_dir: Path,
    project_json_path: Path,
    turns: int,
    no_llm: bool,
    reconfig: bool,
) -> Optional[ProjectConfig]:
    """
    Return a valid ProjectConfig. Creates project.json if needed.
    Returns None if the user aborts or an error occurs.
    """
    if project_json_path.exists() and not reconfig:
        safe_print("Bestehende project.json gefunden — überspringe Discovery.")
        try:
            return ProjectConfig.from_file(str(base_dir))
        except (ValueError, json.JSONDecodeError) as exc:
            safe_print(f"project.json ist ungültig: {exc}", "ERROR")
            return None

    # Discovery required
    data = _discover(base_dir, turns, no_llm)
    if data is None:
        return None

    try:
        return ProjectConfig.create_from_dict(str(base_dir), data, overwrite=reconfig)
    except (ValueError, OSError) as exc:
        safe_print(f"Fehler beim Schreiben der project.json: {exc}", "ERROR")
        return None


def _discover(base_dir: Path, turns: int, no_llm: bool) -> Optional[dict]:
    """Run LLM discovery or guided wizard. Returns a project.json dict or None."""
    if no_llm:
        return run_guided_wizard(base_dir)

    # LLM discovery with wizard fallback
    safe_print("LLM Discovery läuft...")
    loop = LLMDiscoveryLoop(base_dir=base_dir, max_turns=turns)
    result = loop.run()

    if result is None:
        safe_print("LLM Discovery fehlgeschlagen — Wizard-Fallback.", "WARNING")
        return run_guided_wizard(base_dir)

    if not result.skip_confirm:
        _show_preview(result.project_json, result.pipeline_plan)
        response = input("project.json schreiben und Pipeline starten? [y/n]: ").strip().lower()
        if response != "y":
            safe_print("Abgebrochen.")
            return None

    return result.project_json


# ---------------------------------------------------------------------------
# OCR execution
# ---------------------------------------------------------------------------

def _run_pending_ocr(
    base_dir: Path,
    state_map: dict,
    ocr_model: str,
) -> list[Path]:
    """Run OCR for all PDFs with status 'pending'. Returns list of produced .txt paths."""
    pending = [
        base_dir / rel
        for rel, state in state_map.items()
        if state.ocr == "pending"
    ]

    if not pending:
        return []

    safe_print(f"\n--- OCR: {len(pending)} PDF(s) ausstehend ---")

    from .. import pdf2pic as _pdf2pic
    from .. import pic2text as _pic2text

    produced: list[Path] = []
    for pdf_path in pending:
        safe_print(f"  OCR: {pdf_path.name}")
        images_dir = base_dir / "pdf2pic" / pdf_path.stem
        images_dir.mkdir(parents=True, exist_ok=True)
        txt_path = pdf_path.with_suffix(".txt")

        try:
            _pdf2pic.convert_pdf_to_images(
                pdf_path=str(pdf_path),
                output_dir=str(images_dir),
                resume_existing=True,
            )
            _pic2text.convert_images_to_text(
                images_dir=str(images_dir),
                output_file=str(txt_path),
                model_repeats=[(ocr_model, 1)],
            )
            produced.append(txt_path)
        except Exception as exc:
            safe_print(f"  OCR fehlgeschlagen für {pdf_path.name}: {exc}", "ERROR")

    return produced


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_ocr_txts(base_dir: Path, state_map: dict) -> list[str]:
    """Collect absolute paths of OCR-complete .txt files for ingestion."""
    txts = []
    for rel_pdf, state in state_map.items():
        if state.ocr == "done":
            pdf_path = base_dir / rel_pdf
            txt_path = pdf_path.with_suffix(".txt")
            if txt_path.exists():
                txts.append(str(txt_path))
    return txts


def _db_has_cards(base_dir: Path) -> bool:
    db = base_dir / "card_database.json"
    if not db.exists():
        return False
    try:
        data = json.loads(db.read_text(encoding="utf-8"))
        return bool(data.get("cards"))
    except (json.JSONDecodeError, OSError):
        return False


def _print_plan(state_map: dict) -> None:
    safe_print("\n--- Pipeline-Plan ---")
    if not state_map:
        safe_print("  Keine PDFs gefunden.")
        return
    for rel_path, state in sorted(state_map.items()):
        ocr_sym = "✅" if state.ocr == "done" else ("🔄" if state.ocr == "running" else ("⏸" if state.ocr == "paused" else "⏳"))
        ing_sym = "✅" if state.ingest == "done" else "⏳"
        exp_sym = "✅" if state.export == "done" else "⏳"
        safe_print(f"  {rel_path}: OCR{ocr_sym} Ingest{ing_sym} Export{exp_sym}")
    safe_print("")


def _show_preview(project_json: dict, pipeline_plan: list) -> None:
    safe_print("\n--- Generierte project.json (Vorschau) ---")
    safe_print(json.dumps(project_json, indent=2, ensure_ascii=False))
    if pipeline_plan:
        safe_print("\n--- Pipeline-Plan (LLM) ---")
        for step in pipeline_plan:
            safe_print(f"  [{step.get('status','?'):8s}] {step.get('step','?')}: {step.get('file','?')}")
    safe_print("")
