"""Tests for pdf2anki.text2anki.pipeline_state."""
import json
import pytest
from pathlib import Path
from pdf2anki.text2anki.pipeline_state import (
    infer_ocr_status,
    infer_project_state,
    scan_directory,
    PipelineState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_state(txt_path: Path, run_status: str) -> Path:
    state_path = txt_path.with_name(f"{txt_path.name}.ocr_state.json")
    state_path.write_text(
        json.dumps({"run_status": run_status, "pages": {}}), encoding="utf-8"
    )
    return state_path


# ---------------------------------------------------------------------------
# infer_ocr_status
# ---------------------------------------------------------------------------

class TestInferOcrStatus:
    def test_pending_when_no_txt(self, tmp_path):
        assert infer_ocr_status(tmp_path / "out.txt") == "pending"

    def test_done_when_txt_exists_no_state(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("page text", encoding="utf-8")
        assert infer_ocr_status(txt) == "done"

    def test_done_when_state_says_completed(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("page text", encoding="utf-8")
        write_state(txt, "completed")
        assert infer_ocr_status(txt) == "done"

    def test_running_when_state_says_running(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("partial text", encoding="utf-8")
        write_state(txt, "running")
        assert infer_ocr_status(txt) == "running"

    def test_paused_when_state_says_paused(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("partial text", encoding="utf-8")
        write_state(txt, "paused")
        assert infer_ocr_status(txt) == "paused"

    def test_running_when_state_is_corrupt(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("partial text", encoding="utf-8")
        state_path = txt.with_name(f"{txt.name}.ocr_state.json")
        state_path.write_bytes(b"not valid json{{{")
        assert infer_ocr_status(txt) == "running"

    def test_running_when_state_missing_run_status_key(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("x", encoding="utf-8")
        state_path = txt.with_name(f"{txt.name}.ocr_state.json")
        state_path.write_text(json.dumps({"pages": {}}), encoding="utf-8")
        assert infer_ocr_status(txt) == "running"

    def test_pending_when_only_state_exists_no_txt(self, tmp_path):
        # State file without .txt → still pending
        txt = tmp_path / "out.txt"
        write_state(txt, "running")
        assert infer_ocr_status(txt) == "pending"


# ---------------------------------------------------------------------------
# infer_project_state
# ---------------------------------------------------------------------------

class TestInferProjectState:
    def test_both_pending_when_empty_dir(self, tmp_path):
        ingest, export = infer_project_state(tmp_path)
        assert ingest == "pending"
        assert export == "pending"

    def test_ingest_done_when_db_has_cards(self, tmp_path):
        db = tmp_path / "card_database.json"
        db.write_text(json.dumps({"cards": [{"front": "Q", "back": "A"}]}), encoding="utf-8")
        ingest, _ = infer_project_state(tmp_path)
        assert ingest == "done"

    def test_ingest_pending_when_db_empty_cards(self, tmp_path):
        db = tmp_path / "card_database.json"
        db.write_text(json.dumps({"cards": []}), encoding="utf-8")
        ingest, _ = infer_project_state(tmp_path)
        assert ingest == "pending"

    def test_ingest_pending_when_db_corrupt(self, tmp_path):
        db = tmp_path / "card_database.json"
        db.write_bytes(b"not json")
        ingest, _ = infer_project_state(tmp_path)
        assert ingest == "pending"

    def test_export_done_when_apkg_exists(self, tmp_path):
        (tmp_path / "deck.apkg").write_bytes(b"fake apkg")
        _, export = infer_project_state(tmp_path)
        assert export == "done"

    def test_export_pending_when_no_apkg(self, tmp_path):
        _, export = infer_project_state(tmp_path)
        assert export == "pending"


# ---------------------------------------------------------------------------
# scan_directory
# ---------------------------------------------------------------------------

class TestScanDirectory:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert scan_directory(tmp_path) == {}

    def test_single_pdf_no_txt_is_pending(self, tmp_path):
        (tmp_path / "lecture.pdf").write_bytes(b"%PDF")
        result = scan_directory(tmp_path)
        assert "lecture.pdf" in result
        assert result["lecture.pdf"].ocr == "pending"

    def test_single_pdf_with_txt_is_done(self, tmp_path):
        (tmp_path / "lecture.pdf").write_bytes(b"%PDF")
        (tmp_path / "lecture.txt").write_text("text", encoding="utf-8")
        result = scan_directory(tmp_path)
        assert result["lecture.pdf"].ocr == "done"

    def test_ignores_pdf2pic_dir(self, tmp_path):
        pdf2pic = tmp_path / "pdf2pic"
        pdf2pic.mkdir()
        (pdf2pic / "hidden.pdf").write_bytes(b"%PDF")
        result = scan_directory(tmp_path)
        assert result == {}

    def test_ignores_log_archive_dir(self, tmp_path):
        log_archive = tmp_path / "log_archive"
        log_archive.mkdir()
        (log_archive / "archived.pdf").write_bytes(b"%PDF")
        result = scan_directory(tmp_path)
        assert result == {}

    def test_recursive_scan_finds_nested_pdf(self, tmp_path):
        sub = tmp_path / "chapter1"
        sub.mkdir()
        (sub / "vl01.pdf").write_bytes(b"%PDF")
        result = scan_directory(tmp_path)
        assert "chapter1/vl01.pdf" in result or "chapter1\\vl01.pdf" in result

    def test_ocr_running_propagates(self, tmp_path):
        pdf = tmp_path / "vl.pdf"
        pdf.write_bytes(b"%PDF")
        txt = tmp_path / "vl.txt"
        txt.write_text("partial", encoding="utf-8")
        write_state(txt, "running")
        result = scan_directory(tmp_path)
        assert result["vl.pdf"].ocr == "running"

    def test_ingest_and_export_propagate_to_all_pdfs(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF")
        (tmp_path / "b.pdf").write_bytes(b"%PDF")
        db = tmp_path / "card_database.json"
        db.write_text(json.dumps({"cards": [{"front": "Q", "back": "A"}]}), encoding="utf-8")
        (tmp_path / "deck.apkg").write_bytes(b"fake")
        result = scan_directory(tmp_path)
        for state in result.values():
            assert state.ingest == "done"
            assert state.export == "done"

    def test_pipeline_state_is_namedtuple(self, tmp_path):
        (tmp_path / "x.pdf").write_bytes(b"%PDF")
        result = scan_directory(tmp_path)
        state = result["x.pdf"]
        assert isinstance(state, PipelineState)
        assert hasattr(state, "ocr")
        assert hasattr(state, "ingest")
        assert hasattr(state, "export")
