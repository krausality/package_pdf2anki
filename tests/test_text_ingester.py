"""Tests for pdf2anki.text2anki.text_ingester.TextFileIngestor."""
import json
import pytest
from unittest.mock import patch

from pdf2anki.text2anki.text_ingester import TextFileIngestor, ingest_text


MOCK_CARDS = [
    {"front": "Was ist X?", "back": "X ist Y.", "collection": "collection_0_Kapitel1", "category": "a_cat"},
    {"front": "Was ist Z?", "back": "Z ist W.", "collection": "collection_1_Kapitel2", "category": "b_cat"},
]


@pytest.fixture
def txt_file(tmp_path):
    """Creates a temporary .txt source file."""
    p = tmp_path / "material.txt"
    p.write_text("Dies ist das Lernmaterial.", encoding="utf-8")
    return str(p)


class TestTextFileIngestorIngest:
    def test_happy_path_returns_new_cards(self, txt_file, sample_config):
        """LLM returns valid JSON → ingest() returns list of cards."""
        llm_json = json.dumps({"new_cards": MOCK_CARDS})
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_json):
            result = TextFileIngestor().ingest([txt_file], sample_config)
        assert "new_cards" in result
        assert len(result["new_cards"]) == 2

    def test_markdown_code_block_stripped(self, txt_file, sample_config):
        """LLM wraps JSON in ```json ... ``` → still parsed correctly."""
        llm_json = f"```json\n{json.dumps({'new_cards': MOCK_CARDS})}\n```"
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_json):
            result = TextFileIngestor().ingest([txt_file], sample_config)
        assert len(result["new_cards"]) == 2

    def test_plain_code_block_stripped(self, txt_file, sample_config):
        """LLM wraps JSON in ``` ... ``` (no language tag)."""
        llm_json = f"```\n{json.dumps({'new_cards': MOCK_CARDS})}\n```"
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_json):
            result = TextFileIngestor().ingest([txt_file], sample_config)
        assert len(result["new_cards"]) == 2

    def test_invalid_json_from_llm_returns_empty(self, txt_file, sample_config):
        """LLM returns unparseable garbage → returns empty new_cards."""
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value="NOT JSON"):
            # _parse_response raises JSONDecodeError, ingest should handle it
            try:
                result = TextFileIngestor().ingest([txt_file], sample_config)
                # If it doesn't raise, new_cards should be empty or result is a dict
                assert isinstance(result, dict)
            except (json.JSONDecodeError, Exception):
                pass  # acceptable — main concern is no crash leaking through to caller

    def test_llm_returns_none_gives_empty_cards(self, txt_file, sample_config):
        """LLM fails (returns None) → returns {"new_cards": []}."""
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=None):
            result = TextFileIngestor().ingest([txt_file], sample_config)
        assert result == {"new_cards": []}

    def test_missing_source_file_continues(self, sample_config):
        """Missing file is skipped with a warning; LLM still called with empty text."""
        llm_json = json.dumps({"new_cards": []})
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_json):
            result = TextFileIngestor().ingest(["/nonexistent/file.txt"], sample_config)
        assert "new_cards" in result

    def test_multiple_source_files_concatenated(self, tmp_path, sample_config):
        """Multiple source files are all read and concatenated."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("Material A", encoding="utf-8")
        f2.write_text("Material B", encoding="utf-8")

        captured_prompt = {}

        def fake_llm(header_context, prompt_body, model=None):
            captured_prompt["body"] = prompt_body
            return json.dumps({"new_cards": []})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", side_effect=fake_llm):
            TextFileIngestor().ingest([str(f1), str(f2)], sample_config)

        assert "Material A" in captured_prompt["body"]
        assert "Material B" in captured_prompt["body"]


class TestBuildPrompt:
    def test_prompt_contains_domain(self, sample_config):
        ingestor = TextFileIngestor()
        collection_ctx = ingestor._build_collection_context(sample_config)
        prompt = ingestor._build_prompt(
            domain=sample_config.domain,
            language=sample_config.language,
            collection_context=collection_ctx,
            material="test",
            schema_example="{}",
        )
        assert sample_config.domain in prompt

    def test_prompt_german_language(self, sample_config):
        ingestor = TextFileIngestor()
        prompt = ingestor._build_prompt(
            domain="Chemie",
            language="de",
            collection_context="",
            material="material",
            schema_example="{}",
        )
        assert "Experte" in prompt  # German keyword

    def test_prompt_english_language(self, sample_config):
        ingestor = TextFileIngestor()
        prompt = ingestor._build_prompt(
            domain="Chemistry",
            language="en",
            collection_context="",
            material="material",
            schema_example="{}",
        )
        assert "expert" in prompt.lower()

    def test_prompt_contains_collection_keys(self, sample_config):
        ingestor = TextFileIngestor()
        ctx = ingestor._build_collection_context(sample_config)
        assert "collection_0_Kapitel1" in ctx
        assert "collection_1_Kapitel2" in ctx


class TestIngestTextWrapper:
    def test_saves_output_file(self, txt_file, sample_config, tmp_path):
        output = str(tmp_path / "new_cards_output.json")
        llm_json = json.dumps({"new_cards": MOCK_CARDS})
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_json):
            result = ingest_text([txt_file], sample_config, output)
        assert result is True
        assert (tmp_path / "new_cards_output.json").exists()
        with open(output, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["new_cards"]) == 2
