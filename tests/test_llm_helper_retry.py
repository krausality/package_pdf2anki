"""Retry policy for transient upstream failures in llm_helper.

The policy under test (see the constants block in llm_helper.py):
retry 429/500/502/503 -- whether they arrive as an HTTP status or as an
OpenRouterStreamError code from a mid-stream SSE error event -- with bounded,
jittered backoff (2 attempts after the first); everything else fails
immediately into the existing None-and-log path. time.sleep is mocked
throughout: these tests assert the *decisions* (retry vs. fail-fast, how
often, roughly how long) without ever waiting.
"""
import json
import pytest
import requests as req
from unittest.mock import patch, MagicMock

import pdf2anki.text2anki.llm_helper as lh
from pdf2anki.openrouter_transport import OpenRouterStreamError
from pdf2anki.text2anki.llm_helper import (
    get_llm_decision,
    get_llm_conversation_turn,
    get_session_responses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_response(content: str = "ok") -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"cost": 0.001, "prompt_tokens_details": {"cached_tokens": 0}},
    }
    return mock


def _http_error_response(status_code: int) -> MagicMock:
    """Eager error response as the transport returns it for non-SSE errors:
    raise_for_status raises an HTTPError that carries the response."""
    mock = MagicMock()
    mock.status_code = status_code
    err = req.exceptions.HTTPError(f"{status_code} error")
    err.response = mock
    mock.raise_for_status.side_effect = err
    return mock


def _stream_error(code):
    return OpenRouterStreamError(
        f"OpenRouter mid-stream error (HTTP status was already 200): "
        f"code={code}, message=synthetic", code=code)


@pytest.fixture(autouse=True)
def _llm_state():
    original = lh.API_KEY
    lh.API_KEY = "test-key"
    lh.reset_llm_session()
    yield
    lh.API_KEY = original
    lh.reset_llm_session()


@pytest.fixture(autouse=True)
def _no_sleep():
    """Backoff must never actually wait in tests; capture the durations."""
    with patch("pdf2anki.text2anki.llm_helper.time.sleep") as sleep_mock:
        yield sleep_mock


# ---------------------------------------------------------------------------
# Retryable failures are retried
# ---------------------------------------------------------------------------

class TestRetryableFailures:
    def test_midstream_429_is_retried_then_succeeds(self, _no_sleep):
        """The production incident: upstream rate limit as a mid-stream SSE
        error event (OpenRouterStreamError code=429). One transient hit must
        not turn the call into None -- it must be retried and succeed."""
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_stream_error(429), _ok_response("answer")]) as post:
            result = get_llm_decision("h", "b")

        assert result == "answer"
        assert post.call_count == 2
        assert _no_sleep.call_count == 1
        # First delay is 2.0s with +/-25% jitter.
        assert 1.5 <= _no_sleep.call_args_list[0].args[0] <= 2.5

    def test_http_status_429_is_retried_then_succeeds(self, _no_sleep):
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_http_error_response(429), _ok_response()]) as post:
            result = get_llm_decision("h", "b")

        assert result == "ok"
        assert post.call_count == 2

    def test_transient_503_is_retried(self, _no_sleep):
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_http_error_response(503), _ok_response()]) as post:
            result = get_llm_decision("h", "b")

        assert result == "ok"
        assert post.call_count == 2

    def test_exhausted_retries_return_none_with_backoff_growth(self, _no_sleep):
        """Three 429s in a row: initial call + 2 retries, then the existing
        error path (None + session error entry). The second delay must be
        longer than the first (8s vs 2s base, jitter notwithstanding)."""
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_stream_error(429)] * 3) as post:
            result = get_llm_decision("h", "b")

        assert result is None
        assert post.call_count == 3
        assert _no_sleep.call_count == 2
        first, second = (c.args[0] for c in _no_sleep.call_args_list)
        assert 1.5 <= first <= 2.5
        assert 6.0 <= second <= 10.0
        assert second > first
        errors = get_session_responses()
        assert len(errors) == 1 and "error" in errors[0]


# ---------------------------------------------------------------------------
# Non-retryable failures fail fast
# ---------------------------------------------------------------------------

class TestNonRetryableFailures:
    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
    def test_deterministic_4xx_fails_immediately(self, _no_sleep, status):
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   return_value=_http_error_response(status)) as post:
            result = get_llm_decision("h", "b")

        assert result is None
        assert post.call_count == 1
        assert _no_sleep.call_count == 0

    def test_premature_eof_code_none_is_not_retried(self, _no_sleep):
        """OpenRouterStreamError with code=None is truncation, not throttling:
        retrying would re-bill a full generation for a transport-shape
        problem. It must take the fail-fast path."""
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=OpenRouterStreamError(
                       "stream ended prematurely", code=None)) as post:
            result = get_llm_decision("h", "b")

        assert result is None
        assert post.call_count == 1
        assert _no_sleep.call_count == 0

    def test_guard_timeout_is_not_retried(self, _no_sleep):
        """Idle/wall guard Timeouts exist to make stuck generations loud;
        silently re-running a call that just burned minutes would hide that."""
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=req.exceptions.Timeout("idle guard")) as post:
            result = get_llm_decision("h", "b")

        assert result is None
        assert post.call_count == 1
        assert _no_sleep.call_count == 0

    def test_connection_error_is_not_retried(self, _no_sleep):
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=req.exceptions.ConnectionError("down")) as post:
            result = get_llm_decision("h", "b")

        assert result is None
        assert post.call_count == 1
        assert _no_sleep.call_count == 0

    def test_http_error_without_response_fails_fast(self, _no_sleep):
        """An HTTPError carrying no response (as some tests and edge paths
        produce) has no status to classify -- must not be retried."""
        bad = MagicMock()
        bad.raise_for_status.side_effect = req.exceptions.HTTPError("bare")
        bad.raise_for_status.side_effect.response = None
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   return_value=bad) as post:
            result = get_llm_decision("h", "b")

        assert result is None
        assert post.call_count == 1


# ---------------------------------------------------------------------------
# Conversation turns share the policy
# ---------------------------------------------------------------------------

class TestConversationTurnRetry:
    def test_transient_429_retried_history_appended(self, _no_sleep):
        history = []
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_stream_error(429), _ok_response("reply")]) as post:
            reply = get_llm_conversation_turn(history, "question")

        assert reply == "reply"
        assert post.call_count == 2
        assert history == [{"role": "user", "content": "question"},
                           {"role": "assistant", "content": "reply"}]

    def test_exhausted_retries_roll_back_history(self, _no_sleep):
        history = [{"role": "system", "content": "sys"}]
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_stream_error(429)] * 3) as post:
            reply = get_llm_conversation_turn(history, "question")

        assert reply is None
        assert post.call_count == 3
        assert history == [{"role": "system", "content": "sys"}]

    def test_retry_resends_identical_payload(self, _no_sleep):
        """The retried request must be byte-identical to the original -- the
        user message must not be appended twice into the sent payload."""
        history = []
        with patch("pdf2anki.text2anki.llm_helper._http_post",
                   side_effect=[_stream_error(429), _ok_response("r")]) as post:
            get_llm_conversation_turn(history, "q")

        first = json.loads(post.call_args_list[0].kwargs["data"])
        second = json.loads(post.call_args_list[1].kwargs["data"])
        assert first == second
        assert first["messages"] == [{"role": "user", "content": "q"}]
