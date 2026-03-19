"""
lazy_runner.py — Entry point for `pdf2anki .` lazy mode.

Scans the working directory, discovers/creates project.json via LLM or wizard,
infers pipeline state, generates an ordered execution plan, and runs pending steps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from .pipeline_state import scan_directory, infer_ocr_status
from .pipeline_trace import PipelineTrace
from .project_config import ProjectConfig
from .console_utils import safe_print
from .forensic_logger import (
    init_forensic_log, close_forensic_log, set_phase, get_forensic_log_path,
)
from .llm_discovery import LLMDiscoveryLoop
from .llm_helper import reset_llm_session, get_session_responses
from .guided_wizard import run_guided_wizard
from .workflow_manager import WorkflowManager

_DEFAULT_OCR_MODEL = "google/gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_lazy_mode(
    base_dir: Path,
    turns: int = 7,
    no_llm: bool = False,
    reconfig: bool = False,
    ocr_model: Optional[str] = None,
    auto_confirm: bool = False,
) -> None:
    """
    Full lazy-mode pipeline for `pdf2anki .`.

    Args:
        base_dir:  Directory to scan and operate in.
        turns:     Max LLM discovery turns (ignored when no_llm=True).
        no_llm:    If True, use the guided CLI wizard instead of LLM discovery.
        reconfig:  If True, re-run discovery even if project.json already exists.
        ocr_model: OCR model to use for pending PDFs. Defaults to gemini-2.5-flash.
        auto_confirm: If True, skip interactive y/n confirmation prompts.
    """
    base_dir = base_dir.resolve()
    ocr_model = ocr_model or _DEFAULT_OCR_MODEL

    trace = PipelineTrace(base_dir / "pipeline_trace.json")
    trace.begin_run()

    # Initialize forensic log for this run
    log_archive = base_dir / "log_archive"
    run_id = (trace._current_run or {}).get("run_id", "run")
    init_forensic_log(log_archive, run_id)

    safe_print(f"\n=== pdf2anki . (lazy mode) — {base_dir} ===\n")

    try:
        # ── Phase 1: Discovery ────────────────────────────────────────────
        trace.begin_phase("discovery")
        set_phase("discovery")
        reset_llm_session()

        project_json_path = base_dir / "project.json"
        config, discovery_meta = _ensure_project_config(
            base_dir=base_dir,
            project_json_path=project_json_path,
            turns=turns,
            no_llm=no_llm,
            reconfig=reconfig,
            auto_confirm=auto_confirm,
        )
        if config is None:
            safe_print("Aborted: project.json could not be created.", "ERROR")
            trace.end_phase("discovery", "failed",
                            {"error": "project.json could not be created", **discovery_meta},
                            get_session_responses())
            trace.end_run("failed", "Discovery failed")
            return

        discovery_meta["project_json_shape"] = {
            "collections": len(config.collections),
            "domain": config.domain,
        }
        trace.end_phase("discovery", "ok", discovery_meta, get_session_responses())

        # ── Phase 2: Pipeline state + OCR ─────────────────────────────────
        state_map = scan_directory(base_dir)
        _print_plan(state_map)

        manager = WorkflowManager(project_dir=str(base_dir))

        trace.begin_phase("ocr")
        set_phase("ocr")
        pending_count = sum(1 for s in state_map.values() if s.ocr == "pending")
        skipped_count = sum(1 for s in state_map.values() if s.ocr == "done")
        ocr_done_txts = _run_pending_ocr(base_dir, state_map, ocr_model)
        trace.end_phase("ocr", "ok", {
            "note": "Detailed OCR logs in log_archive/",
            "pdfs_processed": len(ocr_done_txts),
            "pdfs_already_done": skipped_count,
            "pdfs_pending_before": pending_count,
        })

        # ── Phase 3: Ingest ───────────────────────────────────────────────
        state_map = scan_directory(base_dir)  # re-scan after OCR
        txt_files = _collect_ocr_txts(base_dir, state_map)

        if txt_files:
            trace.begin_phase("ingest")
            set_phase("ingest")
            reset_llm_session()

            safe_print(f"\n--- Ingest: {len(txt_files)} Datei(en) ---")
            manager.run_ingest_workflow(txt_files)

            ingest_meta = _read_ingest_results(base_dir, config, txt_files)
            trace.end_phase("ingest", "ok", ingest_meta, get_session_responses())

            # ── Phase 4: Integrate ────────────────────────────────────────
            trace.begin_phase("integrate")
            set_phase("integrate")
            reset_llm_session()

            safe_print("\n--- Integrate ---")
            pre_count = len(manager.db_manager.cards)
            manager.run_integrate_workflow(skip_gate=True)
            post_count = len(manager.db_manager.cards)

            trace.end_phase("integrate", "ok", {
                "gate_check": "skipped",
                "cards_submitted": ingest_meta.get("cards_generated", 0),
                "cards_added": post_count - pre_count,
            }, get_session_responses())

            # Balance check after integration
            balance_warnings = manager.db_manager.check_distribution_balance()
            for w in balance_warnings:
                safe_print(f"  -> {w}", "WARNING")
                log_event("distribution_balance_warning", {"warning": w})

        # ── Phase 5: Export ───────────────────────────────────────────────
        state_map = scan_directory(base_dir)
        if any(s.ingest == "done" for s in state_map.values()) or _db_has_cards(base_dir):
            trace.begin_phase("export")
            set_phase("export")

            safe_print("\n--- Export ---")
            manager.run_export_workflow()

            export_meta = _read_export_results(config, manager.db_manager)
            trace.end_phase("export", "ok", export_meta)

        safe_print("\n=== pdf2anki . abgeschlossen ===")
        _print_cost_summary(trace)
        forensic_path = get_forensic_log_path()
        if forensic_path:
            safe_print(f"  Forensic log: {forensic_path}")
        safe_print("")
        close_forensic_log()
        trace.end_run("ok")

    except Exception as exc:
        close_forensic_log()
        trace.end_run("failed", str(exc))
        raise


# ---------------------------------------------------------------------------
# Project config setup
# ---------------------------------------------------------------------------

def _ensure_project_config(
    base_dir: Path,
    project_json_path: Path,
    turns: int,
    no_llm: bool,
    reconfig: bool,
    auto_confirm: bool = False,
) -> tuple[Optional[ProjectConfig], dict]:
    """
    Return a valid ProjectConfig and discovery metadata.
    Returns (None, meta) if the user aborts or an error occurs.
    """
    meta: dict = {}

    if project_json_path.exists() and not reconfig:
        safe_print("Bestehende project.json gefunden — überspringe Discovery.")
        meta["method"] = "existing"
        try:
            return ProjectConfig.from_file(str(base_dir)), meta
        except (ValueError, json.JSONDecodeError) as exc:
            safe_print(f"project.json ist ungültig: {exc}", "ERROR")
            meta["error"] = str(exc)
            return None, meta

    # Discovery required
    data, discover_meta = _discover(base_dir, turns, no_llm, auto_confirm)
    meta.update(discover_meta)
    if data is None:
        return None, meta

    try:
        return ProjectConfig.create_from_dict(str(base_dir), data, overwrite=reconfig), meta
    except (ValueError, OSError) as exc:
        safe_print(f"Fehler beim Schreiben der project.json: {exc}", "ERROR")
        meta["error"] = str(exc)
        return None, meta


def _discover(base_dir: Path, turns: int, no_llm: bool,
              auto_confirm: bool = False) -> tuple[Optional[dict], dict]:
    """Run LLM discovery or guided wizard. Returns (project_json_dict, metadata)."""
    meta: dict = {}

    if no_llm:
        meta["method"] = "wizard"
        return run_guided_wizard(base_dir), meta

    # Fail fast: detect non-interactive stdin BEFORE expensive LLM calls
    if not auto_confirm and not sys.stdin.isatty():
        safe_print(
            "Kein interaktiver Input möglich. Nutze --yes / -y für automatische Bestätigung.",
            "ERROR",
        )
        safe_print("Tipp: pdf2anki . -y")
        return None, meta

    # LLM discovery with wizard fallback
    safe_print("LLM Discovery läuft...")
    meta["method"] = "llm"
    loop = LLMDiscoveryLoop(base_dir=base_dir, max_turns=turns)
    result = loop.run()
    meta["turns"] = loop.turns_used
    meta["tool_calls"] = loop.tool_calls_made

    if result is None:
        safe_print("LLM Discovery fehlgeschlagen — Wizard-Fallback.", "WARNING")
        meta["method"] = "llm_then_wizard"
        return run_guided_wizard(base_dir), meta

    if not result.skip_confirm and not auto_confirm:
        _show_preview(result.project_json, result.pipeline_plan)
        try:
            response = input("project.json schreiben und Pipeline starten? [y/n]: ").strip().lower()
        except EOFError:
            safe_print("Kein interaktiver Input möglich. Nutze --yes / -y für automatische Bestätigung.", "ERROR")
            return None, meta
        if response != "y":
            safe_print("Abgebrochen.")
            return None, meta
    elif auto_confirm and not result.skip_confirm:
        _show_preview(result.project_json, result.pipeline_plan)
        safe_print("  (--yes: automatisch bestätigt)")

    return result.project_json, meta


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
# Trace helpers
# ---------------------------------------------------------------------------

def _read_ingest_results(base_dir: Path, config: ProjectConfig, txt_files: list) -> dict:
    """Read new_cards_output.json to extract card counts for trace."""
    meta: dict = {
        "source_files": [Path(f).name for f in txt_files],
        "model": config.get_llm_model(),
        "cards_generated": 0,
        "cards_per_collection": {},
    }
    try:
        new_cards_path = config.get_new_cards_path()
        with open(new_cards_path, encoding="utf-8") as f:
            data = json.load(f)
        cards = data.get("new_cards", data if isinstance(data, list) else [])
        meta["cards_generated"] = len(cards)
        for card in cards:
            coll = card.get("collection", "unknown")
            meta["cards_per_collection"][coll] = meta["cards_per_collection"].get(coll, 0) + 1
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return meta


def _read_export_results(config: ProjectConfig, db_manager) -> dict:
    """Build export metadata from db_manager card state."""
    collections: dict[str, int] = {}
    for card in db_manager.cards:
        collections[card.collection] = collections.get(card.collection, 0) + 1

    files = []
    for coll_key, count in sorted(collections.items()):
        coll_cfg = config.collections.get(coll_key, {})
        filename = coll_cfg.get("filename", f"{coll_key}.json").replace(".json", ".apkg")
        files.append({"path": filename, "card_count": count})

    return {"files_generated": files}


# ---------------------------------------------------------------------------
# General helpers
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
        # card_database.json is a flat array of card objects, not {"cards": [...]}
        if isinstance(data, list):
            return len(data) > 0
        return bool(data.get("cards") if isinstance(data, dict) else False)
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


def _print_cost_summary(trace: PipelineTrace) -> None:
    """Print a one-line cost summary from the current run's accumulated LLM data."""
    try:
        run = trace._runs[-1] if trace._runs else None
        if run is None:
            return
        total_cost = 0.0
        total_calls = 0
        for phase in run.get("phases", {}).values():
            for call in phase.get("llm_calls", []):
                total_cost += call.get("cost", 0)
                total_calls += 1
        if total_calls > 0:
            safe_print(f"  Kosten: ~${total_cost:.3f} ({total_calls} LLM-Calls)")
    except Exception:
        pass


def _show_preview(project_json: dict, pipeline_plan: list) -> None:
    safe_print("\n--- Generierte project.json (Vorschau) ---")
    safe_print(json.dumps(project_json, indent=2, ensure_ascii=False))
    if pipeline_plan:
        safe_print("\n--- Pipeline-Plan (LLM) ---")
        for step in pipeline_plan:
            safe_print(f"  [{step.get('status','?'):8s}] {step.get('step','?')}: {step.get('file','?')}")
    safe_print("")
