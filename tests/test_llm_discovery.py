"""Tests for llm_discovery.LLMDiscoveryLoop."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pdf2anki.text2anki.llm_discovery import LLMDiscoveryLoop, DiscoveryResult


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

MINIMAL_PROJECT_JSON = {
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
            "description": "Grundlagen",
        }
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}

FINAL_RESPONSE = json.dumps({
    "final": {
        "project_json": MINIMAL_PROJECT_JSON,
        "skip_confirm": False,
        "pipeline_plan": [
            {"step": "ocr", "file": "lecture.pdf", "status": "pending"}
        ],
    }
})

TOOL_CALL_RESPONSE = json.dumps({
    "tool_call": {"name": "list_directory", "args": {}}
})


def _loop(tmp_path, max_turns=5) -> LLMDiscoveryLoop:
    return LLMDiscoveryLoop(base_dir=tmp_path, max_turns=max_turns)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_parses_final(self, tmp_path):
        loop = _loop(tmp_path)
        kind, data = loop._parse_response(FINAL_RESPONSE)
        assert kind == "final"
        assert "project_json" in data

    def test_parses_tool_call(self, tmp_path):
        loop = _loop(tmp_path)
        kind, data = loop._parse_response(TOOL_CALL_RESPONSE)
        assert kind == "tool_call"
        assert data["name"] == "list_directory"

    def test_strips_markdown_fences(self, tmp_path):
        loop = _loop(tmp_path)
        wrapped = f"```json\n{FINAL_RESPONSE}\n```"
        kind, _ = loop._parse_response(wrapped)
        assert kind == "final"

    def test_returns_unknown_on_garbage(self, tmp_path):
        loop = _loop(tmp_path)
        kind, data = loop._parse_response("Sorry I cannot help with that.")
        assert kind == "unknown"
        assert data == {}

    def test_returns_unknown_on_invalid_json(self, tmp_path):
        loop = _loop(tmp_path)
        kind, _ = loop._parse_response("{not valid json}")
        assert kind == "unknown"


# ---------------------------------------------------------------------------
# _parse_page_spec
# ---------------------------------------------------------------------------

class TestParsePageSpec:
    def test_single_page(self, tmp_path):
        assert LLMDiscoveryLoop._parse_page_spec("1") == [0]

    def test_range(self, tmp_path):
        assert LLMDiscoveryLoop._parse_page_spec("1-3") == [0, 1, 2]

    def test_comma_separated(self, tmp_path):
        assert LLMDiscoveryLoop._parse_page_spec("1,3,5") == [0, 2, 4]

    def test_garbage_returns_empty(self, tmp_path):
        assert LLMDiscoveryLoop._parse_page_spec("abc") == []


# ---------------------------------------------------------------------------
# Tool methods
# ---------------------------------------------------------------------------

class TestToolListDirectory:
    def test_lists_pdfs(self, tmp_path):
        (tmp_path / "lecture.pdf").write_bytes(b"%PDF")
        loop = _loop(tmp_path)
        result = loop._tool_list_directory()
        assert "lecture.pdf" in result

    def test_ignores_pdf2pic(self, tmp_path):
        (tmp_path / "pdf2pic").mkdir()
        (tmp_path / "pdf2pic" / "hidden.pdf").write_bytes(b"%PDF")
        loop = _loop(tmp_path)
        result = loop._tool_list_directory()
        assert "hidden.pdf" not in result

    def test_shows_ocr_status(self, tmp_path):
        (tmp_path / "vl.pdf").write_bytes(b"%PDF")
        (tmp_path / "vl.txt").write_text("text", encoding="utf-8")
        loop = _loop(tmp_path)
        result = loop._tool_list_directory()
        assert "OCR: done" in result


class TestToolReadTxtExcerpt:
    def test_reads_lines(self, tmp_path):
        txt = tmp_path / "out.txt"
        txt.write_text("line1\nline2\nline3\n", encoding="utf-8")
        loop = _loop(tmp_path)
        result = loop._tool_read_txt_excerpt("out.txt", lines=2)
        assert "line1" in result
        assert "line2" in result
        assert "line3" not in result

    def test_file_not_found(self, tmp_path):
        loop = _loop(tmp_path)
        result = loop._tool_read_txt_excerpt("missing.txt")
        assert "ERROR" in result


class TestToolReadPdfPages:
    def test_file_not_found(self, tmp_path):
        loop = _loop(tmp_path)
        result = loop._tool_read_pdf_pages("missing.pdf")
        assert "ERROR" in result

    def test_non_pdf_rejected(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        loop = _loop(tmp_path)
        result = loop._tool_read_pdf_pages("file.txt")
        assert "ERROR" in result

    def test_calls_fitz(self, tmp_path):
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-fake")
        loop = _loop(tmp_path)
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Lecture content"
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=10)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        with patch("fitz.open", return_value=mock_doc):
            result = loop._tool_read_pdf_pages("doc.pdf", "1")
        assert "Lecture content" in result


# ---------------------------------------------------------------------------
# run() — full loop
# ---------------------------------------------------------------------------

class TestRun:
    def test_returns_discovery_result_on_immediate_final(self, tmp_path):
        loop = _loop(tmp_path)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            return_value=FINAL_RESPONSE,
        ):
            result = loop.run()

        assert isinstance(result, DiscoveryResult)
        assert result.project_json["project_name"] == "TestProjekt"

    def test_skip_confirm_propagated(self, tmp_path):
        confident = json.dumps({
            "final": {
                "project_json": MINIMAL_PROJECT_JSON,
                "skip_confirm": True,
                "pipeline_plan": [],
            }
        })
        loop = _loop(tmp_path)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            return_value=confident,
        ):
            result = loop.run()
        assert result.skip_confirm is True

    def test_tool_call_then_final(self, tmp_path):
        # After fix: tool result is deferred, not sent via API — only 2 calls needed
        responses = [TOOL_CALL_RESPONSE, FINAL_RESPONSE]
        loop = _loop(tmp_path, max_turns=5)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            side_effect=responses,
        ):
            result = loop.run()
        assert result is not None
        assert result.project_json["project_name"] == "TestProjekt"

    def test_tool_call_saves_one_api_call(self, tmp_path):
        """Tool result deferral eliminates the redundant API call."""
        responses = [TOOL_CALL_RESPONSE, FINAL_RESPONSE]
        loop = _loop(tmp_path, max_turns=5)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            side_effect=responses,
        ) as mock_turn:
            loop.run()
        # Exactly 2 API calls: initial turn + tool-result turn
        assert mock_turn.call_count == 2

    def test_returns_none_when_api_fails(self, tmp_path):
        loop = _loop(tmp_path)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            return_value=None,
        ):
            result = loop.run()
        assert result is None

    def test_returns_none_when_max_turns_exhausted(self, tmp_path):
        loop = _loop(tmp_path, max_turns=2)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            return_value='{"unknown": "garbage"}',
        ):
            result = loop.run()
        assert result is None

    def test_template_defaults_merged_into_sparse_project_json(self, tmp_path):
        sparse = json.dumps({
            "final": {
                "project_json": {
                    "project_name": "Sparse",
                    "tag_prefix": "SP",
                    "collections": {
                        "collection_0_X": {
                            "display_name": "X",
                            "filename": "collection_0_X.json",
                            "description": "",
                        }
                    },
                },
                "skip_confirm": False,
                "pipeline_plan": [],
            }
        })
        loop = _loop(tmp_path)
        with patch(
            "pdf2anki.text2anki.llm_discovery.get_llm_conversation_turn",
            return_value=sparse,
        ):
            result = loop.run()
        assert result is not None
        assert "files" in result.project_json  # merged from template
