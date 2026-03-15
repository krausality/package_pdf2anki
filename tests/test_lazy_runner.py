"""Tests for lazy_runner.run_lazy_mode()."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from pdf2anki.text2anki.lazy_runner import run_lazy_mode
from pdf2anki.text2anki.llm_discovery import DiscoveryResult

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_PROJECT_JSON = {
    "project_name": "TestProjekt",
    "tag_prefix": "TEST",
    "language": "de",
    "domain": "Informatik",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt",
    },
    "collections": {
        "collection_0_Kap1": {
            "display_name": "Kapitel 1",
            "filename": "collection_0_Kap1.json",
            "description": "",
        }
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}

DISCOVERY_RESULT = DiscoveryResult(
    project_json=VALID_PROJECT_JSON,
    skip_confirm=True,
    pipeline_plan=[],
)


def _write_project_json(directory: Path, data: dict = None) -> None:
    data = data or VALID_PROJECT_JSON
    (directory / "project.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _patch_wm():
    """Context manager that patches WorkflowManager methods."""
    return patch(
        "pdf2anki.text2anki.lazy_runner.WorkflowManager",
        autospec=True,
    )


def _configure_mock_loop(mock_loop_cls, result=None):
    """Set required attributes on a mocked LLMDiscoveryLoop instance."""
    instance = mock_loop_cls.return_value
    instance.run.return_value = result
    instance.turns_used = 1
    instance.tool_calls_made = []
    return instance


# ---------------------------------------------------------------------------
# Tests: project.json already exists (no reconfig)
# ---------------------------------------------------------------------------

class TestExistingProjectJson:
    def test_loads_existing_config_without_discovery(self, tmp_path):
        _write_project_json(tmp_path)
        with _patch_wm() as MockWM:
            MockWM.return_value.run_ingest_workflow.return_value = True
            MockWM.return_value.run_integrate_workflow.return_value = True
            MockWM.return_value.run_export_workflow.return_value = True
            with patch("pdf2anki.text2anki.lazy_runner.LLMDiscoveryLoop") as MockLoop:
                run_lazy_mode(tmp_path)
                MockLoop.assert_not_called()

    def test_reconfig_triggers_discovery(self, tmp_path):
        _write_project_json(tmp_path)
        with _patch_wm() as MockWM:
            MockWM.return_value.run_ingest_workflow.return_value = True
            MockWM.return_value.run_integrate_workflow.return_value = True
            MockWM.return_value.run_export_workflow.return_value = True
            with patch(
                "pdf2anki.text2anki.lazy_runner.LLMDiscoveryLoop"
            ) as MockLoop:
                _configure_mock_loop(MockLoop, DISCOVERY_RESULT)
                run_lazy_mode(tmp_path, reconfig=True)
                MockLoop.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: first run — no project.json
# ---------------------------------------------------------------------------

class TestFirstRun:
    def test_llm_discovery_called_when_no_project_json(self, tmp_path):
        with _patch_wm() as MockWM:
            MockWM.return_value.run_ingest_workflow.return_value = True
            MockWM.return_value.run_integrate_workflow.return_value = True
            MockWM.return_value.run_export_workflow.return_value = True
            with patch(
                "pdf2anki.text2anki.lazy_runner.LLMDiscoveryLoop"
            ) as MockLoop:
                _configure_mock_loop(MockLoop, DISCOVERY_RESULT)
                run_lazy_mode(tmp_path)
                MockLoop.assert_called_once()

    def test_wizard_called_when_no_llm(self, tmp_path):
        with _patch_wm() as MockWM:
            MockWM.return_value.run_ingest_workflow.return_value = True
            MockWM.return_value.run_integrate_workflow.return_value = True
            MockWM.return_value.run_export_workflow.return_value = True
            with patch(
                "pdf2anki.text2anki.lazy_runner.run_guided_wizard",
                return_value=VALID_PROJECT_JSON,
            ) as mock_wiz:
                run_lazy_mode(tmp_path, no_llm=True)
                mock_wiz.assert_called_once()

    def test_falls_back_to_wizard_when_llm_returns_none(self, tmp_path):
        with _patch_wm() as MockWM:
            MockWM.return_value.run_ingest_workflow.return_value = True
            MockWM.return_value.run_integrate_workflow.return_value = True
            MockWM.return_value.run_export_workflow.return_value = True
            with patch(
                "pdf2anki.text2anki.lazy_runner.LLMDiscoveryLoop"
            ) as MockLoop:
                _configure_mock_loop(MockLoop, None)
                with patch(
                    "pdf2anki.text2anki.lazy_runner.run_guided_wizard",
                    return_value=VALID_PROJECT_JSON,
                ) as mock_wiz:
                    run_lazy_mode(tmp_path)
                    mock_wiz.assert_called_once()

    def test_aborts_cleanly_when_user_declines_preview(self, tmp_path):
        """When skip_confirm=False and user says 'n', should not write project.json."""
        non_confident = DiscoveryResult(
            project_json=VALID_PROJECT_JSON,
            skip_confirm=False,
            pipeline_plan=[],
        )
        with patch(
            "pdf2anki.text2anki.lazy_runner.LLMDiscoveryLoop"
        ) as MockLoop:
            _configure_mock_loop(MockLoop, non_confident)
            with patch("builtins.input", return_value="n"):
                run_lazy_mode(tmp_path)
        assert not (tmp_path / "project.json").exists()


# ---------------------------------------------------------------------------
# Tests: pipeline step execution
# ---------------------------------------------------------------------------

class TestPipelineExecution:
    def test_ingest_and_integrate_called_for_ocr_done_txts(self, tmp_path):
        _write_project_json(tmp_path)
        # Create a PDF+TXT pair with OCR done (no state file → archived)
        (tmp_path / "vl.pdf").write_bytes(b"%PDF")
        (tmp_path / "vl.txt").write_text("content", encoding="utf-8")

        with _patch_wm() as MockWM:
            instance = MockWM.return_value
            instance.run_ingest_workflow.return_value = True
            instance.run_integrate_workflow.return_value = True
            instance.run_export_workflow.return_value = True
            instance.db_manager = MagicMock()
            instance.db_manager.cards = []
            run_lazy_mode(tmp_path)
            instance.run_ingest_workflow.assert_called_once()
            instance.run_integrate_workflow.assert_called_once()

    def test_export_called_when_db_has_cards(self, tmp_path):
        _write_project_json(tmp_path)
        db = tmp_path / "card_database.json"
        db.write_text(json.dumps({"cards": [{"front": "Q", "back": "A"}]}), encoding="utf-8")

        with _patch_wm() as MockWM:
            instance = MockWM.return_value
            instance.run_ingest_workflow.return_value = True
            instance.run_integrate_workflow.return_value = True
            instance.run_export_workflow.return_value = True
            instance.db_manager = MagicMock()
            instance.db_manager.cards = []
            run_lazy_mode(tmp_path)
            instance.run_export_workflow.assert_called_once()

    def test_no_ingest_when_no_ocr_txts(self, tmp_path):
        _write_project_json(tmp_path)
        # PDF exists but no TXT yet
        (tmp_path / "vl.pdf").write_bytes(b"%PDF")

        with _patch_wm() as MockWM:
            instance = MockWM.return_value
            # Mock the OCR step to avoid real pdf2pic/pic2text calls
            with patch("pdf2anki.text2anki.lazy_runner._run_pending_ocr", return_value=[]):
                run_lazy_mode(tmp_path)
            instance.run_ingest_workflow.assert_not_called()

    def test_turns_passed_to_discovery_loop(self, tmp_path):
        with _patch_wm() as MockWM:
            MockWM.return_value.run_ingest_workflow.return_value = True
            MockWM.return_value.run_integrate_workflow.return_value = True
            MockWM.return_value.run_export_workflow.return_value = True
            with patch(
                "pdf2anki.text2anki.lazy_runner.LLMDiscoveryLoop"
            ) as MockLoop:
                _configure_mock_loop(MockLoop, DISCOVERY_RESULT)
                run_lazy_mode(tmp_path, turns=7)
                MockLoop.assert_called_once_with(base_dir=tmp_path.resolve(), max_turns=7)
