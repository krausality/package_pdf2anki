"""Tests for ProjectConfig.create_from_dict()."""
import json
import pytest
from pathlib import Path
from pdf2anki.text2anki.project_config import ProjectConfig


VALID_DATA = {
    "project_name": "TestProjekt",
    "tag_prefix": "TEST",
    "language": "de",
    "domain": "Testwissen",
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
            "description": "Grundlagen",
        }
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}


class TestCreateFromDict:
    def test_writes_project_json(self, tmp_path):
        ProjectConfig.create_from_dict(str(tmp_path), VALID_DATA)
        assert (tmp_path / "project.json").exists()

    def test_returns_project_config_instance(self, tmp_path):
        cfg = ProjectConfig.create_from_dict(str(tmp_path), VALID_DATA)
        assert isinstance(cfg, ProjectConfig)
        assert cfg.project_name == "TestProjekt"

    def test_written_json_is_valid(self, tmp_path):
        ProjectConfig.create_from_dict(str(tmp_path), VALID_DATA)
        data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
        assert data["project_name"] == "TestProjekt"
        assert "collection_0_Kap1" in data["collections"]

    def test_creates_project_dir_if_absent(self, tmp_path):
        target = tmp_path / "new_subdir"
        ProjectConfig.create_from_dict(str(target), VALID_DATA)
        assert target.is_dir()
        assert (target / "project.json").exists()

    def test_raises_file_exists_error_when_exists_and_no_overwrite(self, tmp_path):
        ProjectConfig.create_from_dict(str(tmp_path), VALID_DATA)
        with pytest.raises(FileExistsError):
            ProjectConfig.create_from_dict(str(tmp_path), VALID_DATA, overwrite=False)

    def test_overwrite_true_replaces_existing(self, tmp_path):
        ProjectConfig.create_from_dict(str(tmp_path), VALID_DATA)
        updated = {**VALID_DATA, "project_name": "UpdatedName"}
        cfg = ProjectConfig.create_from_dict(str(tmp_path), updated, overwrite=True)
        assert cfg.project_name == "UpdatedName"

    def test_raises_value_error_on_missing_project_name(self, tmp_path):
        bad = {k: v for k, v in VALID_DATA.items() if k != "project_name"}
        with pytest.raises(ValueError, match="project_name"):
            ProjectConfig.create_from_dict(str(tmp_path), bad)

    def test_raises_value_error_on_collection_missing_filename(self, tmp_path):
        bad = {
            **VALID_DATA,
            "collections": {
                "col0": {"display_name": "X", "description": "Y"}  # no filename
            },
        }
        with pytest.raises(ValueError, match="filename"):
            ProjectConfig.create_from_dict(str(tmp_path), bad)

    def test_does_not_write_on_validation_failure(self, tmp_path):
        bad = {k: v for k, v in VALID_DATA.items() if k != "project_name"}
        with pytest.raises(ValueError):
            ProjectConfig.create_from_dict(str(tmp_path), bad)
        assert not (tmp_path / "project.json").exists()
