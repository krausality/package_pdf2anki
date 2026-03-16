"""Integration tests: verify forensic log_event wiring actually produces JSONL output.

These tests run real code paths (with mocked LLM) and assert that the expected
forensic events land in the JSONL file. Catches silent breakage if an import
is refactored or log_event calls are accidentally removed.
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pdf2anki.text2anki.forensic_logger import (
    init_forensic_log,
    close_forensic_log,
    set_phase,
    get_forensic_log_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_events(log_dir: Path, run_id: str) -> list[dict]:
    """Read all JSONL events from a forensic log file."""
    path = log_dir / "forensic" / f"{run_id}.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def _make_api_response(content: str = "ok", cost: float = 0.001) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"cost": cost, "prompt_tokens_details": {"cached_tokens": 0}},
    }
    return mock


@pytest.fixture(autouse=True)
def clean_logger():
    """Ensure forensic logger is closed before and after each test."""
    close_forensic_log()
    yield
    close_forensic_log()


@pytest.fixture(autouse=True)
def set_api_key():
    import pdf2anki.text2anki.llm_helper as lh
    original = lh.API_KEY
    lh.API_KEY = "test-key"
    lh.reset_llm_session()
    yield
    lh.API_KEY = original
    lh.reset_llm_session()


# ---------------------------------------------------------------------------
# Test: get_llm_decision wiring
# ---------------------------------------------------------------------------

class TestLlmHelperWiring:
    def test_get_llm_decision_logs_request_and_response(self, tmp_path):
        init_forensic_log(tmp_path, "wiring-llm")
        set_phase("ingest")

        from pdf2anki.text2anki.llm_helper import get_llm_decision
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_api_response('{"cards": []}')):
            get_llm_decision("header", "body", json_mode=True)

        close_forensic_log()
        events = _read_events(tmp_path, "wiring-llm")
        event_types = [e["event"] for e in events]

        assert "llm_request" in event_types
        assert "llm_response" in event_types

        req = next(e for e in events if e["event"] == "llm_request")
        assert req["phase"] == "ingest"
        assert req["data"]["caller"] == "get_llm_decision"
        assert req["data"]["json_mode"] is True
        assert "header" in req["data"]["prompt"]

    def test_get_llm_decision_logs_error(self, tmp_path):
        import requests as req_lib
        init_forensic_log(tmp_path, "wiring-err")

        from pdf2anki.text2anki.llm_helper import get_llm_decision
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=req_lib.exceptions.ConnectionError("down")):
            get_llm_decision("h", "b")

        close_forensic_log()
        events = _read_events(tmp_path, "wiring-err")
        event_types = [e["event"] for e in events]

        assert "llm_request" in event_types
        assert "llm_error" in event_types

    def test_conversation_turn_logs_events(self, tmp_path):
        init_forensic_log(tmp_path, "wiring-conv")
        set_phase("discovery")

        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn
        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_api_response("reply")):
            get_llm_conversation_turn(history, "hello")

        close_forensic_log()
        events = _read_events(tmp_path, "wiring-conv")
        event_types = [e["event"] for e in events]

        assert "llm_request" in event_types
        assert "llm_response" in event_types

        req = next(e for e in events if e["event"] == "llm_request")
        assert req["data"]["caller"] == "get_llm_conversation_turn"
        assert req["phase"] == "discovery"


# ---------------------------------------------------------------------------
# Test: text_ingester wiring
# ---------------------------------------------------------------------------

class TestIngesterWiring:
    def test_ingest_logs_prompt_and_parse_strategy(self, tmp_path):
        init_forensic_log(tmp_path, "wiring-ingest")
        set_phase("ingest")

        from pdf2anki.text2anki.text_ingester import TextFileIngestor
        from pdf2anki.text2anki.project_config import ProjectConfig

        # Create a minimal .txt source
        src = tmp_path / "material.txt"
        src.write_text("Some lecture content about automata.", encoding="utf-8")

        # Create minimal project config
        config = MagicMock(spec=ProjectConfig)
        config.domain = "Computer Science"
        config.language = "en"
        config.collections = {
            "collection_0_Automata": {
                "display_name": "Automata",
                "filename": "collection_0_Automata.json",
            }
        }
        config.get_llm_model.return_value = "test/model"

        llm_response = json.dumps({
            "new_cards": [{"front": "What is a DFA?", "back": "A deterministic finite automaton.",
                           "collection": "collection_0_Automata", "category": "a_basics"}]
        })

        ingestor = TextFileIngestor()
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=llm_response):
            result = ingestor.ingest([str(src)], config)

        close_forensic_log()
        events = _read_events(tmp_path, "wiring-ingest")
        event_types = [e["event"] for e in events]

        assert "ingest_prompt" in event_types
        assert "ingest_response_raw" in event_types
        assert "ingest_parse" in event_types

        parse_evt = next(e for e in events if e["event"] == "ingest_parse")
        assert parse_evt["data"]["success"] is True
        assert parse_evt["data"]["card_count"] == 1

    def test_ingest_logs_parse_failure(self, tmp_path):
        init_forensic_log(tmp_path, "wiring-ingest-fail")

        from pdf2anki.text2anki.text_ingester import TextFileIngestor

        src = tmp_path / "mat.txt"
        src.write_text("content", encoding="utf-8")

        config = MagicMock()
        config.domain = "X"
        config.language = "en"
        config.collections = {}
        config.get_llm_model.return_value = "m"

        ingestor = TextFileIngestor()
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value="this is not json at all"):
            result = ingestor.ingest([str(src)], config)

        close_forensic_log()
        events = _read_events(tmp_path, "wiring-ingest-fail")

        parse_evt = next(e for e in events if e["event"] == "ingest_parse")
        assert parse_evt["data"]["success"] is False
        assert parse_evt["data"]["strategy"] == "all_failed"


# ---------------------------------------------------------------------------
# Test: phase context propagation
# ---------------------------------------------------------------------------

class TestPhaseContext:
    def test_phase_propagates_through_events(self, tmp_path):
        """Events logged under different phases carry the correct phase tag."""
        init_forensic_log(tmp_path, "wiring-phases")

        from pdf2anki.text2anki.llm_helper import get_llm_decision

        set_phase("discovery")
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_api_response("disc_reply")):
            get_llm_decision("h", "b")

        set_phase("ingest")
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_api_response("ing_reply")):
            get_llm_decision("h", "b")

        close_forensic_log()
        events = _read_events(tmp_path, "wiring-phases")

        requests = [e for e in events if e["event"] == "llm_request"]
        assert len(requests) == 2
        assert requests[0]["phase"] == "discovery"
        assert requests[1]["phase"] == "ingest"
