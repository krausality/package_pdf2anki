"""Tests for pdf2anki.text2anki.project_config.ProjectConfig."""
import json
import pytest

from pdf2anki.text2anki.project_config import ProjectConfig

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

VALID_DATA = {
    "project_name": "MeinTest",
    "tag_prefix": "MEINTEST",
    "language": "de",
    "domain": "Chemie",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
    },
    "collections": {
        "collection_0_K1": {
            "display_name": "K1: Grundlagen",
            "filename": "collection_0_K1.json",
            "description": "Basics",
        }
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.2},
}


def write_project_json(tmp_path, data):
    p = tmp_path / "project.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# from_file
# ─────────────────────────────────────────────────────────────────────────────

class TestFromFile:
    def test_happy_path(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert cfg.project_name == "MeinTest"
        assert cfg.tag_prefix == "MEINTEST"
        assert cfg.language == "de"
        assert cfg.domain == "Chemie"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ProjectConfig.from_file(str(tmp_path))

    def test_invalid_json_raises(self, tmp_path):
        (tmp_path / "project.json").write_text("NOT { JSON", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            ProjectConfig.from_file(str(tmp_path))

    def test_missing_project_name_raises(self, tmp_path):
        bad = dict(VALID_DATA)
        del bad["project_name"]
        write_project_json(tmp_path, bad)
        with pytest.raises(ValueError, match="project_name"):
            ProjectConfig.from_file(str(tmp_path))

    def test_missing_tag_prefix_raises(self, tmp_path):
        bad = dict(VALID_DATA)
        del bad["tag_prefix"]
        write_project_json(tmp_path, bad)
        with pytest.raises(ValueError, match="tag_prefix"):
            ProjectConfig.from_file(str(tmp_path))

    def test_missing_collections_raises(self, tmp_path):
        bad = dict(VALID_DATA)
        del bad["collections"]
        write_project_json(tmp_path, bad)
        with pytest.raises(ValueError, match="collections"):
            ProjectConfig.from_file(str(tmp_path))

    def test_empty_collections_raises(self, tmp_path):
        bad = {**VALID_DATA, "collections": {}}
        write_project_json(tmp_path, bad)
        with pytest.raises(ValueError, match="collections"):
            ProjectConfig.from_file(str(tmp_path))

    def test_collection_missing_filename_raises(self, tmp_path):
        bad = {
            **VALID_DATA,
            "collections": {"collection_0_K1": {"display_name": "K1"}},
        }
        write_project_json(tmp_path, bad)
        with pytest.raises(ValueError, match="filename"):
            ProjectConfig.from_file(str(tmp_path))

    def test_collection_filename_not_json_raises(self, tmp_path):
        bad = {
            **VALID_DATA,
            "collections": {
                "collection_0_K1": {"display_name": "K1", "filename": "data.txt"}
            },
        }
        write_project_json(tmp_path, bad)
        with pytest.raises(ValueError, match=".json"):
            ProjectConfig.from_file(str(tmp_path))


# ─────────────────────────────────────────────────────────────────────────────
# create_template
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateTemplate:
    def test_creates_project_json(self, tmp_path):
        cfg = ProjectConfig.create_template(str(tmp_path / "myproj"), "MyProject")
        project_json = tmp_path / "myproj" / "project.json"
        assert project_json.exists()
        assert cfg.project_name == "MyProject"

    def test_tag_prefix_uppercased(self, tmp_path):
        cfg = ProjectConfig.create_template(str(tmp_path / "proj"), "my project")
        assert cfg.tag_prefix == "MY_PROJECT"

    def test_raises_if_already_exists(self, tmp_path):
        ProjectConfig.create_template(str(tmp_path), "First")
        with pytest.raises(FileExistsError):
            ProjectConfig.create_template(str(tmp_path), "Second")


# ─────────────────────────────────────────────────────────────────────────────
# Path helper methods
# ─────────────────────────────────────────────────────────────────────────────

class TestPathHelpers:
    def test_get_db_path(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert cfg.get_db_path().endswith("card_database.json")

    def test_get_markdown_path(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert cfg.get_markdown_path().endswith("All_fronts.md")

    def test_get_new_cards_path(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert cfg.get_new_cards_path().endswith("new_cards_output.json")

    def test_paths_are_absolute(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        import os
        assert os.path.isabs(cfg.get_db_path())
        assert os.path.isabs(cfg.get_markdown_path())


# ─────────────────────────────────────────────────────────────────────────────
# Collection helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectionHelpers:
    def test_get_collection_filename_mapping(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        mapping = cfg.get_collection_filename_mapping()
        assert "collection_0_K1" in mapping
        assert mapping["collection_0_K1"] == "collection_0_K1.json"

    def test_get_legacy_collection_files(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        files = cfg.get_legacy_collection_files()
        assert len(files) == 1
        assert files[0].endswith("collection_0_K1.json")

    def test_get_llm_model(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert cfg.get_llm_model() == "google/gemini-2.5-flash"

    def test_get_llm_temperature(self, tmp_path):
        write_project_json(tmp_path, VALID_DATA)
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert cfg.get_llm_temperature() == pytest.approx(0.2)

    def test_defaults_without_llm_section(self, tmp_path):
        data = {**VALID_DATA}
        del data["llm"]
        write_project_json(tmp_path, data)
        cfg = ProjectConfig.from_file(str(tmp_path))
        # Should return defaults without crashing
        model = cfg.get_llm_model()
        assert isinstance(model, str)
