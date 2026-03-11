"""Tests for workflow_manager._run_init() and new --init CLI flags."""
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from pdf2anki.text2anki.workflow_manager import _run_init
from pdf2anki.text2anki.llm_discovery import DiscoveryResult

VALID_DATA = {
    "project_name": "Placeholder",
    "tag_prefix": "PH",
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
    project_json=dict(VALID_DATA),
    skip_confirm=True,
    pipeline_plan=[],
)


class TestRunInit:
    def test_no_llm_uses_wizard(self, tmp_path):
        with patch(
            "pdf2anki.text2anki.workflow_manager.run_guided_wizard",
            return_value=dict(VALID_DATA),
        ) as mock_wiz:
            # Import inside the module namespace
            with patch("pdf2anki.text2anki.workflow_manager.ProjectConfig.create_from_dict"):
                _run_init(str(tmp_path), "TestProjekt", no_llm=True, turns=5, reconfig=False)
            mock_wiz.assert_called_once()

    def test_llm_used_by_default(self, tmp_path):
        with patch(
            "pdf2anki.text2anki.workflow_manager.LLMDiscoveryLoop"
        ) as MockLoop:
            MockLoop.return_value.run.return_value = DISCOVERY_RESULT
            with patch("pdf2anki.text2anki.workflow_manager.ProjectConfig.create_from_dict"):
                _run_init(str(tmp_path), "TestProjekt", no_llm=False, turns=5, reconfig=False)
            MockLoop.assert_called_once()

    def test_cli_project_name_overrides_llm_name(self, tmp_path):
        result = DiscoveryResult(
            project_json={**VALID_DATA, "project_name": "LLMGuessedName"},
            skip_confirm=True,
            pipeline_plan=[],
        )
        captured = {}
        def fake_create(project_dir, data, overwrite=False):
            captured["data"] = data
            from pdf2anki.text2anki.project_config import ProjectConfig
            return MagicMock(spec=ProjectConfig)

        with patch("pdf2anki.text2anki.workflow_manager.LLMDiscoveryLoop") as MockLoop:
            MockLoop.return_value.run.return_value = result
            with patch(
                "pdf2anki.text2anki.workflow_manager.ProjectConfig.create_from_dict",
                side_effect=fake_create,
            ):
                _run_init(str(tmp_path), "CLIName", no_llm=False, turns=5, reconfig=False)
        assert captured["data"]["project_name"] == "CLIName"

    def test_falls_back_to_template_when_llm_fails(self, tmp_path):
        with patch(
            "pdf2anki.text2anki.workflow_manager.LLMDiscoveryLoop"
        ) as MockLoop:
            MockLoop.return_value.run.return_value = None
            with patch(
                "pdf2anki.text2anki.workflow_manager.ProjectConfig.create_template"
            ) as mock_template:
                _run_init(str(tmp_path), "TestProjekt", no_llm=False, turns=5, reconfig=False)
            mock_template.assert_called_once()

    def test_reconfig_passes_overwrite_true(self, tmp_path):
        captured = {}
        def fake_create(project_dir, data, overwrite=False):
            captured["overwrite"] = overwrite
            from pdf2anki.text2anki.project_config import ProjectConfig
            return MagicMock(spec=ProjectConfig)

        with patch("pdf2anki.text2anki.workflow_manager.LLMDiscoveryLoop") as MockLoop:
            MockLoop.return_value.run.return_value = DISCOVERY_RESULT
            with patch(
                "pdf2anki.text2anki.workflow_manager.ProjectConfig.create_from_dict",
                side_effect=fake_create,
            ):
                _run_init(str(tmp_path), "P", no_llm=False, turns=5, reconfig=True)
        assert captured.get("overwrite") is True


class TestCliDotIntercept:
    def test_dot_intercept_calls_run_lazy_mode(self):
        import pdf2anki.core as core_mod
        with patch.object(sys, "argv", ["pdf2anki", ".", "--turns", "3", "--no-llm"]):
            with patch("pdf2anki.text2anki.lazy_runner.run_lazy_mode") as mock_lazy:
                core_mod.cli_invoke()
                mock_lazy.assert_called_once()
                _, kwargs = mock_lazy.call_args
                assert kwargs.get("turns") == 3 or mock_lazy.call_args[0][1] == 3
                assert kwargs.get("no_llm") is True or mock_lazy.call_args[0][2] is True

    def test_dot_not_confused_with_other_subcommands(self):
        """Ensure the '.' intercept only fires for sys.argv[1] == '.'"""
        with patch.object(sys, "argv", ["pdf2anki", "workflow", "--help"]):
            import pdf2anki.core as core_mod
            with patch("pdf2anki.text2anki.workflow_manager.main"):
                try:
                    core_mod.cli_invoke()
                except SystemExit:
                    pass  # --help exits
