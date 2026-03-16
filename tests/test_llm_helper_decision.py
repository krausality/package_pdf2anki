"""Tests for get_llm_decision() in llm_helper — the main card-generation LLM call."""
import json
import pytest
from unittest.mock import patch, MagicMock, call

import pdf2anki.text2anki.llm_helper as lh
from pdf2anki.text2anki.llm_helper import (
    get_llm_decision,
    reset_llm_session,
    get_session_responses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(content: str, cost: float = 0.001, cached: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "cost": cost,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_module_state():
    """Ensure API_KEY and session state are clean for every test."""
    original_key = lh.API_KEY
    lh.API_KEY = "test-key-fixture"
    lh.reset_llm_session()
    yield
    lh.API_KEY = original_key
    lh.reset_llm_session()


@pytest.fixture(autouse=True)
def reset_verbose():
    from pdf2anki.text2anki.console_utils import set_verbose
    set_verbose(False)
    yield
    set_verbose(False)


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

class TestGetLlmDecisionBasic:
    def test_returns_content_stripped(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("  answer  ")):
            result = get_llm_decision("header", "body")
        assert result == "answer"

    def test_builds_correct_prompt(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok")) as mock_post:
            get_llm_decision("HEADER", "BODY", model="test/model")

        payload = json.loads(mock_post.call_args.kwargs["data"])
        assert "HEADER" in payload["messages"][0]["content"]
        assert "BODY" in payload["messages"][0]["content"]
        assert payload["model"] == "test/model"
        assert payload["temperature"] == 0.1

    def test_session_responses_accumulated(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("a")):
            get_llm_decision("h", "b")
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("b")):
            get_llm_decision("h", "b")

        assert len(get_session_responses()) == 2

    def test_reset_session_clears_responses(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("x")):
            get_llm_decision("h", "b")

        reset_llm_session()
        assert get_session_responses() == []

    def test_session_responses_is_copy(self):
        """Modifying the returned list should not affect internal state."""
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("x")):
            get_llm_decision("h", "b")

        responses = get_session_responses()
        responses.clear()
        assert len(get_session_responses()) == 1


# ---------------------------------------------------------------------------
# json_mode parameter
# ---------------------------------------------------------------------------

class TestJsonMode:
    def test_json_mode_false_no_response_format(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok")) as mock_post:
            get_llm_decision("h", "b", json_mode=False)

        payload = json.loads(mock_post.call_args.kwargs["data"])
        assert "response_format" not in payload

    def test_json_mode_true_sets_response_format(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response('{"cards":[]}')):
            get_llm_decision("h", "b", json_mode=True)

    def test_json_mode_payload_structure(self):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response('{"cards":[]}')):
            pass  # verify via mock

        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("{}")) as mock_post:
            get_llm_decision("h", "b", json_mode=True)

        payload = json.loads(mock_post.call_args.kwargs["data"])
        assert payload["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestGetLlmDecisionErrors:
    def test_returns_none_on_connection_error(self):
        import requests as req
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=req.exceptions.ConnectionError("unreachable")):
            result = get_llm_decision("h", "b")
        assert result is None

    def test_returns_none_on_timeout(self):
        import requests as req
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=req.exceptions.Timeout("timeout")):
            result = get_llm_decision("h", "b")
        assert result is None

    def test_returns_none_on_http_error(self):
        import requests as req
        mock = MagicMock()
        mock.raise_for_status.side_effect = req.exceptions.HTTPError("429")
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=mock):
            result = get_llm_decision("h", "b")
        assert result is None

    def test_error_appended_to_session_responses(self):
        import requests as req
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=req.exceptions.ConnectionError("down")):
            get_llm_decision("h", "b")

        responses = get_session_responses()
        assert len(responses) == 1
        assert "error" in responses[0]

    def test_returns_none_on_missing_choices(self):
        bad = MagicMock()
        bad.json.return_value = {"no_choices": True}
        bad.raise_for_status = MagicMock()
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=bad):
            result = get_llm_decision("h", "b")
        assert result is None

    def test_returns_none_on_empty_choices(self):
        bad = MagicMock()
        bad.json.return_value = {"choices": []}
        bad.raise_for_status = MagicMock()
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=bad):
            result = get_llm_decision("h", "b")
        assert result is None

    def test_returns_none_when_no_api_key(self):
        lh.API_KEY = None
        with patch.object(lh, "_initialize_api_key", return_value=False):
            result = get_llm_decision("h", "b")
        assert result is None


# ---------------------------------------------------------------------------
# API key initialization
# ---------------------------------------------------------------------------

class TestInitializeApiKey:
    def test_env_var_loaded(self):
        lh.API_KEY = None
        with patch("pdf2anki.text2anki.llm_helper.os.getenv",
                   return_value="env-key-123"):
            result = lh._initialize_api_key()
        assert result is True
        assert lh.API_KEY == "env-key-123"

    def test_already_set_returns_true(self):
        lh.API_KEY = "existing"
        result = lh._initialize_api_key()
        assert result is True

    def test_getpass_fallback(self):
        lh.API_KEY = None
        with patch("pdf2anki.text2anki.llm_helper.os.getenv", return_value=None), \
             patch("pdf2anki.text2anki.llm_helper.getpass.getpass",
                   return_value="manual-key"):
            result = lh._initialize_api_key()
        assert result is True
        assert lh.API_KEY == "manual-key"

    def test_empty_getpass_returns_false(self):
        lh.API_KEY = None
        with patch("pdf2anki.text2anki.llm_helper.os.getenv", return_value=None), \
             patch("pdf2anki.text2anki.llm_helper.getpass.getpass",
                   return_value=""):
            result = lh._initialize_api_key()
        assert result is False

    def test_getpass_exception_returns_false(self):
        lh.API_KEY = None
        with patch("pdf2anki.text2anki.llm_helper.os.getenv", return_value=None), \
             patch("pdf2anki.text2anki.llm_helper.getpass.getpass",
                   side_effect=EOFError("no tty")):
            result = lh._initialize_api_key()
        assert result is False


# ---------------------------------------------------------------------------
# Verbose mode interaction
# ---------------------------------------------------------------------------

class TestVerboseGating:
    def test_verbose_off_no_full_response_dump(self, capsys):
        from pdf2anki.text2anki.console_utils import set_verbose
        set_verbose(False)

        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok")):
            get_llm_decision("h", "b")

        out = capsys.readouterr().out
        assert "Full OpenRouter API Response" not in out

    def test_verbose_on_shows_full_response(self, capsys):
        from pdf2anki.text2anki.console_utils import set_verbose
        set_verbose(True)

        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok")):
            get_llm_decision("h", "b")

        out = capsys.readouterr().out
        assert "Full OpenRouter API Response" in out

    def test_cost_always_printed(self, capsys):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok", cost=0.005)):
            get_llm_decision("h", "b")

        out = capsys.readouterr().out
        assert "Cost:" in out
        assert "$0.005" in out

    def test_cached_tokens_printed(self, capsys):
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok", cached=1500)):
            get_llm_decision("h", "b")

        out = capsys.readouterr().out
        assert "1500" in out
