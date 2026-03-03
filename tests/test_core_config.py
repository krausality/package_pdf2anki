"""Tests for pdf2anki.core: load_config, save_config, get_default_model."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


def _import_core_functions(tmp_config_dir):
    """
    Import and reload core so CONFIG_DIR/CONFIG_FILE point to our temp directory.
    We patch the module-level globals after import.
    """
    import pdf2anki.core as core
    return core


class TestLoadConfig:
    def test_no_file_returns_empty_dict(self, tmp_path):
        import pdf2anki.core as core
        with patch.object(core, "CONFIG_DIR", tmp_path), \
             patch.object(core, "CONFIG_FILE", tmp_path / "config.json"):
            result = core.load_config()
        assert result == {}

    def test_valid_json_returned(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"default_model": "openai/gpt-4"}), encoding="utf-8")
        import pdf2anki.core as core
        with patch.object(core, "CONFIG_DIR", tmp_path), \
             patch.object(core, "CONFIG_FILE", config_file):
            result = core.load_config()
        assert result["default_model"] == "openai/gpt-4"

    def test_invalid_json_returns_empty_dict(self, tmp_path, capsys):
        config_file = tmp_path / "config.json"
        config_file.write_text("INVALID JSON", encoding="utf-8")
        import pdf2anki.core as core
        with patch.object(core, "CONFIG_DIR", tmp_path), \
             patch.object(core, "CONFIG_FILE", config_file):
            result = core.load_config()
        assert result == {}

    def test_creates_config_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "new_config_dir"
        config_file = new_dir / "config.json"
        import pdf2anki.core as core
        with patch.object(core, "CONFIG_DIR", new_dir), \
             patch.object(core, "CONFIG_FILE", config_file):
            core.load_config()
        assert new_dir.exists()


class TestSaveConfig:
    def test_writes_json_to_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        import pdf2anki.core as core
        with patch.object(core, "CONFIG_DIR", tmp_path), \
             patch.object(core, "CONFIG_FILE", config_file):
            core.save_config({"default_model": "test/model", "key": "value"})
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["default_model"] == "test/model"
        assert data["key"] == "value"

    def test_creates_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "cfg"
        config_file = new_dir / "config.json"
        import pdf2anki.core as core
        with patch.object(core, "CONFIG_DIR", new_dir), \
             patch.object(core, "CONFIG_FILE", config_file):
            core.save_config({"x": 1})
        assert config_file.exists()

    def test_roundtrip(self, tmp_path):
        config_file = tmp_path / "config.json"
        import pdf2anki.core as core
        original = {"default_model": "gemini/flash", "level": 3}
        with patch.object(core, "CONFIG_DIR", tmp_path), \
             patch.object(core, "CONFIG_FILE", config_file):
            core.save_config(original)
            loaded = core.load_config()
        assert loaded == original


class TestGetDefaultModel:
    def test_returns_model_from_config(self):
        import pdf2anki.core as core
        config = {"default_model": "mymodel/v1"}
        result = core.get_default_model(config, interactive=False)
        assert result == "mymodel/v1"

    def test_returns_none_when_no_model_non_interactive(self):
        import pdf2anki.core as core
        config = {}
        result = core.get_default_model(config, interactive=False)
        assert result is None

    def test_empty_string_model_prompts_again(self):
        import pdf2anki.core as core
        config = {"default_model": ""}
        result = core.get_default_model(config, interactive=False)
        assert result is None
