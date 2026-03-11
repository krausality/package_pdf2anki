"""Tests for get_llm_conversation_turn() in llm_helper."""
import json
import pytest
from unittest.mock import patch, MagicMock


def _make_response(content: str, cost: float = 0.0001) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"cost": cost},
    }
    return mock


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_module_state():
    """Ensure API_KEY and session state are clean for every test."""
    import pdf2anki.text2anki.llm_helper as lh
    original_key = lh.API_KEY
    lh.API_KEY = "test-key-fixture"
    lh.reset_llm_session()
    yield
    lh.API_KEY = original_key
    lh.reset_llm_session()


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

class TestGetLlmConversationTurn:
    def test_returns_assistant_content(self):
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("Hello!")):
            reply = get_llm_conversation_turn(history, "Hi there")

        assert reply == "Hello!"

    def test_history_accumulates_user_and_assistant(self):
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("Turn 1 reply")):
            get_llm_conversation_turn(history, "Turn 1 message")

        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Turn 1 message"}
        assert history[1] == {"role": "assistant", "content": "Turn 1 reply"}

    def test_multi_turn_accumulation(self):
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        history = []
        replies = ["Reply A", "Reply B"]
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=[_make_response(r) for r in replies]):
            get_llm_conversation_turn(history, "Msg A")
            get_llm_conversation_turn(history, "Msg B")

        assert len(history) == 4
        assert history[2] == {"role": "user", "content": "Msg B"}
        assert history[3] == {"role": "assistant", "content": "Reply B"}

    def test_full_history_sent_to_api(self):
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        history = [{"role": "system", "content": "You are helpful."}]
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("ok")) as mock_post:
            get_llm_conversation_turn(history, "question")

        payload = json.loads(mock_post.call_args.kwargs["data"])
        assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
        assert payload["messages"][1] == {"role": "user", "content": "question"}

    def test_session_responses_appended(self):
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn, get_session_responses

        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   return_value=_make_response("x")):
            get_llm_conversation_turn(history, "y")

        assert len(get_session_responses()) == 1

    # -----------------------------------------------------------------------
    # Error handling
    # -----------------------------------------------------------------------

    def test_returns_none_on_request_exception(self):
        import requests as req
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=req.exceptions.ConnectionError("unreachable")):
            reply = get_llm_conversation_turn(history, "msg")

        assert reply is None

    def test_history_not_polluted_on_request_error(self):
        import requests as req
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post",
                   side_effect=req.exceptions.ConnectionError("unreachable")):
            get_llm_conversation_turn(history, "msg")

        # User message must be rolled back so history stays consistent
        assert history == []

    def test_returns_none_on_bad_response_structure(self):
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        bad = MagicMock()
        bad.status_code = 200
        bad.json.return_value = {"unexpected": "structure"}
        bad.raise_for_status = MagicMock()

        history = []
        with patch("pdf2anki.text2anki.llm_helper.requests.post", return_value=bad):
            reply = get_llm_conversation_turn(history, "msg")

        assert reply is None
        assert history == []

    def test_returns_none_when_no_api_key(self):
        import pdf2anki.text2anki.llm_helper as lh
        from pdf2anki.text2anki.llm_helper import get_llm_conversation_turn

        lh.API_KEY = None
        history = []
        with patch.object(lh, "_initialize_api_key", return_value=False):
            reply = get_llm_conversation_turn(history, "msg")

        assert reply is None
        assert history == []
