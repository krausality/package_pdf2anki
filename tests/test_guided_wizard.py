"""Tests for guided_wizard.run_guided_wizard()."""
import pytest
from pathlib import Path
from unittest.mock import patch


def _run_wizard(base_dir: Path, inputs: list[str]) -> dict:
    with patch("builtins.input", side_effect=inputs):
        from pdf2anki.text2anki.guided_wizard import run_guided_wizard
        return run_guided_wizard(base_dir)


class TestRunGuidedWizard:
    def _inputs_single_collection(self, **overrides) -> list[str]:
        defaults = [
            "MeinProjekt",   # project_name
            "MEINPROJEKT",   # tag_prefix
            "de",            # language
            "Informatik",    # domain
            "",              # orphan (default)
            "1",             # n_collections
            "Kapitel 1: Grundlagen",  # display_name
            "Einführung",    # description
        ]
        return defaults

    def test_returns_dict(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert isinstance(result, dict)

    def test_project_name_set(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert result["project_name"] == "MeinProjekt"

    def test_tag_prefix_set(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert result["tag_prefix"] == "MEINPROJEKT"

    def test_default_tag_prefix_derived_from_name(self, tmp_path):
        inputs = [
            "Mein Projekt",  # project_name
            "",              # tag_prefix → default derived
            "de",
            "Informatik",
            "",
            "1",
            "Kapitel 1",
            "",
        ]
        result = _run_wizard(tmp_path, inputs)
        assert result["tag_prefix"] == "MEIN_PROJEKT"

    def test_language_set(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert result["language"] == "de"

    def test_domain_set(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert result["domain"] == "Informatik"

    def test_single_collection_created(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert len(result["collections"]) == 1

    def test_collection_has_required_fields(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        col = next(iter(result["collections"].values()))
        assert "display_name" in col
        assert "filename" in col
        assert "description" in col

    def test_collection_filename_ends_with_json(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        col = next(iter(result["collections"].values()))
        assert col["filename"].endswith(".json")

    def test_collection_key_matches_filename_stem(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        for key, col in result["collections"].items():
            stem = col["filename"].removesuffix(".json")
            assert stem == key

    def test_multiple_collections(self, tmp_path):
        inputs = [
            "GTI", "", "de", "Informatik", "",
            "2",               # n_collections
            "Automaten", "",   # col 0
            "Turing", "",      # col 1
        ]
        result = _run_wizard(tmp_path, inputs)
        assert len(result["collections"]) == 2

    def test_files_block_present(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert "files" in result
        assert "db_path" in result["files"]

    def test_llm_block_present(self, tmp_path):
        result = _run_wizard(tmp_path, self._inputs_single_collection())
        assert "llm" in result
        assert "model" in result["llm"]

    def test_empty_project_name_retries(self, tmp_path):
        """Blank input must be rejected until a valid value is provided."""
        inputs = [
            "",              # blank → retry
            "ValidName",     # accepted
            "", "de", "Domain", "", "1", "Kap1", "",
        ]
        result = _run_wizard(tmp_path, inputs)
        assert result["project_name"] == "ValidName"
