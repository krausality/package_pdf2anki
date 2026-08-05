"""Transport guards for text2anki.llm_helper, verified over real sockets.

These tests replay the measured OpenRouter wire behavior (SSE keep-alive
comment lines every fraction of a second, data events, [DONE]) from a local
scripted HTTP server, and drive it through the REAL shared transport
(pdf2anki.openrouter_transport._http_post) via the REAL llm_helper functions.
The only fake is the URL: `_http_post` is wrapped so the hardcoded OpenRouter
URL is redirected to 127.0.0.1 -- everything below it (requests Session,
urllib3, socket reads, SSE consumption, guards) is production code.

The central regression here: requests' `timeout=` is a per-socket-read
inactivity timeout. A connection that dribbles keep-alives forever never goes
quiet, so that timeout can never fire -- the bug that hung an OCR run
indefinitely. The idle-timeout guard must abort such a call even though bytes
keep arriving.
"""
import json
import socket
import threading
import time
from unittest.mock import patch

import pytest

import pdf2anki.openrouter_transport as transport
import pdf2anki.text2anki.llm_helper as lh
from pdf2anki.text2anki.llm_helper import (
    get_llm_decision,
    get_llm_conversation_turn,
    get_session_responses,
)


# ---------------------------------------------------------------------------
# Scripted local server
# ---------------------------------------------------------------------------

class ScriptedServer:
    """Minimal HTTP server: one scripted behavior per accepted connection.

    The behavior callable receives (conn, request_bytes) after the full
    request (headers + Content-Length body) has been read. The response body
    is close-delimited (Connection: close, no Content-Length), which is how a
    long-lived streaming response looks to urllib3.
    """

    def __init__(self, behavior):
        self.behavior = behavior
        self.requests = []  # raw request bytes, one entry per connection
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _read_request(self, conn):
        conn.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return data
            data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        while len(body) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk
        return head + b"\r\n\r\n" + body

    def _serve(self):
        self._sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                request = self._read_request(conn)
                self.requests.append(request)
                self.behavior(conn, self._stop)
            except OSError:
                pass  # client dropped the connection (expected on guard trips)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self):
        self._stop.set()
        self._thread.join(timeout=5)
        try:
            self._sock.close()
        except OSError:
            pass

    def last_payload(self):
        body = self.requests[-1].partition(b"\r\n\r\n")[2]
        return json.loads(body.decode("utf-8"))


# OpenRouter delivers SSE over chunked transfer-encoding (each keep-alive /
# event in its own chunk) -- urllib3 2.x then yields per received chunk, which
# is exactly what re-arms the guards' deadline checks promptly. A
# close-delimited body would instead be buffered up to chunk_size and blur the
# timing, so the scripted server frames chunks explicitly.
SSE_HEAD = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/event-stream\r\n"
    b"Transfer-Encoding: chunked\r\n"
    b"Connection: close\r\n"
    b"\r\n"
)


def _chunk(b):
    return f"{len(b):x}\r\n".encode() + b + b"\r\n"


def keepalives_forever(conn, stop):
    """The measured hang: the socket never goes quiet, but no data event ever
    arrives. Interval scaled down from the measured ~0.4s to keep tests fast;
    what matters is dribble interval << any read/idle timeout."""
    conn.sendall(SSE_HEAD)
    while not stop.is_set():
        time.sleep(0.05)
        conn.sendall(_chunk(b": OPENROUTER PROCESSING\n\n"))


def happy_stream(content_pieces, usage=None):
    def behavior(conn, stop):
        conn.sendall(SSE_HEAD)
        conn.sendall(_chunk(b": OPENROUTER PROCESSING\n\n"))
        for i, piece in enumerate(content_pieces):
            ev = {"id": "gen-local", "model": "test/model",
                  "choices": [{"index": 0, "delta": {"content": piece},
                               "finish_reason": "stop" if i == len(content_pieces) - 1 else None}]}
            conn.sendall(_chunk(b"data: " + json.dumps(ev).encode("utf-8") + b"\n\n"))
            time.sleep(0.01)
        if usage is not None:
            conn.sendall(_chunk(b"data: " + json.dumps({"id": "gen-local", "choices": [], "usage": usage}).encode("utf-8") + b"\n\n"))
        conn.sendall(_chunk(b"data: [DONE]\n\n") + b"0\r\n\r\n")
    return behavior


@pytest.fixture(autouse=True)
def _llm_state():
    original = lh.API_KEY
    lh.API_KEY = "test-key"
    lh.reset_llm_session()
    yield
    lh.API_KEY = original
    lh.reset_llm_session()


def _redirected_transport(port):
    """Real transport, real socket -- only the hardcoded URL is rewritten."""
    def redirect(**kwargs):
        kwargs["url"] = f"http://127.0.0.1:{port}/api/v1/chat/completions"
        return transport._http_post(**kwargs)
    return patch("pdf2anki.text2anki.llm_helper._http_post", side_effect=redirect)


# ---------------------------------------------------------------------------
# The regression proof
# ---------------------------------------------------------------------------

class TestKeepaliveHangIsBounded:
    def test_endless_keepalive_without_progress_is_aborted(self):
        """A connection that dribbles keep-alives forever but never produces a
        data event must be aborted by the idle guard -- get_llm_decision
        returns None promptly instead of blocking its thread indefinitely.

        Note the per-read timeout (60s) never fires here: bytes arrive every
        0.05s. Only the idle guard distinguishes 'alive socket' from
        'progressing generation'. Before the transport routing this call shape
        (requests.post, timeout=60) had no bound at all."""
        server = ScriptedServer(keepalives_forever)
        # Watchdog: this test proves a hang is bounded -- but if the idle
        # guard regresses, the very call under test hangs (only the wall
        # ceiling, 30min, would end it), so the test can never turn red on
        # its own; it blocks the pytest run instead of reporting. The timer
        # closes the server from outside after 5s: the hanging call then dies
        # with a transport error, the call returns, and the elapsed assertion
        # below goes red. Deliberately NOT a worker thread with
        # fut.result(timeout=...): the worker would stay blocked and hang the
        # pytest process at exit -- the exact failure mode this project
        # rejected before. cancel() in finally because Timer threads are
        # non-daemon; left running they delay process exit.
        watchdog = threading.Timer(5.0, server.close)
        watchdog.start()
        try:
            started = time.monotonic()
            with _redirected_transport(server.port), \
                 patch.object(transport, "HTTP_STREAM_IDLE_TIMEOUT_SECONDS", 0.3):
                result = get_llm_decision("header", "body")
            elapsed = time.monotonic() - started
        finally:
            watchdog.cancel()
            server.close()

        assert result is None
        # Lower bound: the guard waited out its idle window (not an instant
        # transport error); upper bound: it fired promptly once the window
        # passed, instead of blocking for as long as keep-alives arrive.
        assert 0.3 <= elapsed < 3, f"idle guard must bound the call, took {elapsed:.2f}s"
        errors = get_session_responses()
        assert len(errors) == 1 and "error" in errors[0]
        assert "no data event" in errors[0]["error"]

    def test_conversation_turn_rolls_back_history_on_keepalive_hang(self):
        """Same guard through get_llm_conversation_turn: the Timeout must take
        the existing RequestException path, so the in-place history mutation
        is rolled back and the caller can retry cleanly."""
        server = ScriptedServer(keepalives_forever)
        # Same watchdog rationale as above. The elapsed bound below is what
        # actually turns this test red under an idle-guard regression: once
        # the watchdog closes the server, the call returns None and the
        # history IS rolled back -- indistinguishable from the guard firing.
        # Only the time bound tells "guard aborted promptly" apart from
        # "watchdog rescued a hang after 5s".
        watchdog = threading.Timer(5.0, server.close)
        watchdog.start()
        started = time.monotonic()
        history = [{"role": "system", "content": "sys"}]
        try:
            with _redirected_transport(server.port), \
                 patch.object(transport, "HTTP_STREAM_IDLE_TIMEOUT_SECONDS", 0.3):
                reply = get_llm_conversation_turn(history, "question")
        finally:
            watchdog.cancel()
            server.close()

        assert time.monotonic() - started < 3, "idle guard must bound the call"
        assert reply is None
        assert history == [{"role": "system", "content": "sys"}]


# ---------------------------------------------------------------------------
# Healthy path over the wire
# ---------------------------------------------------------------------------

class TestHealthyStreamOverSockets:
    def test_decision_json_mode_payload_and_result_survive_sse_upgrade(self):
        """End-to-end: llm_helper's payload vocabulary (usage.include,
        response_format json_object) must survive the transport's silent
        stream upgrade, and the assembled SSE deltas must come back through
        the unchanged .json() parsing -- including the usage/cost bookkeeping
        read from the final usage event."""
        usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
                 "cost": 0.00042, "prompt_tokens_details": {"cached_tokens": 2}}
        server = ScriptedServer(happy_stream(['{"decision"', ': "keep"}'], usage=usage))
        try:
            with _redirected_transport(server.port):
                result = get_llm_decision("h", "b", model="test/model", json_mode=True)
        finally:
            server.close()

        assert result == '{"decision": "keep"}'
        sent = server.last_payload()
        assert sent["stream"] is True  # transport upgraded the call
        assert sent["stream_options"] == {"include_usage": True}
        assert sent["response_format"] == {"type": "json_object"}  # caller vocab intact
        assert sent["usage"] == {"include": True}
        recorded = get_session_responses()[0]
        assert recorded["usage"]["cost"] == 0.00042
        assert recorded["choices"][0]["finish_reason"] == "stop"

    def test_conversation_turn_appends_history_from_streamed_reply(self):
        server = ScriptedServer(happy_stream(["Hel", "lo"]))
        history = []
        try:
            with _redirected_transport(server.port):
                reply = get_llm_conversation_turn(history, "Hi")
        finally:
            server.close()

        assert reply == "Hello"
        assert history == [{"role": "user", "content": "Hi"},
                           {"role": "assistant", "content": "Hello"}]
        sent = server.last_payload()
        assert sent["messages"] == [{"role": "user", "content": "Hi"}]
        assert sent["stream"] is True
